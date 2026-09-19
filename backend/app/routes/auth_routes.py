# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Request, status
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr
import random
import smtplib
import logging
import os
from email.mime.text import MIMEText
from datetime import datetime, timedelta

from app.deps import get_db
from app import models, schemas
from app.utils import hash_password, verify_password
from app.models import RoleEnum, EmailOTP
from app.auth import create_access_token, get_current_user, RoleChecker
from app.config import load_env
from app.rate_limit import client_ip, check_rate_limit, reset_rate_limit

# Load .env variables (anchored to the project root)
load_env()

logger = logging.getLogger("recruito.auth")

# Gmail SMTP defaults, overridable via .env for other providers.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# Candidate signup email OTP verification. SECURE DEFAULT: ON (required).
#
# OTP verification is implemented and fully preserved; when enabled, candidate
# signup requires a valid, unexpired 6-digit OTP and the SMTP service in
# .env (EMAIL_ADDRESS / EMAIL_PASSWORD) must be configured to send it.
#
# For LOCAL DEVELOPMENT / TESTING only, set BYPASS_EMAIL_OTP=true in .env to
# skip sending and checking the OTP. Production must leave it unset or false.
BYPASS_EMAIL_OTP = os.getenv("BYPASS_EMAIL_OTP", "false").strip().lower() in ("1", "true", "yes", "on")

# ----------------------------
# Rate Limiting Config
# ----------------------------
# In-memory sliding-window rate limiting for auth endpoints (send/resend OTP,
# login). State never touches the DB and resets on process restart.
# Defaults: ON, 5 login attempts / 5 min, 3 OTP requests / 60s per IP + email.
# Disable only for local development/testing via RATE_LIMIT_ENABLED=false.
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))
OTP_MAX_REQUESTS = int(os.getenv("OTP_MAX_REQUESTS", "3"))
OTP_WINDOW_SECONDS = int(os.getenv("OTP_WINDOW_SECONDS", "60"))

router = APIRouter()

# Roles a user is allowed to self-register as.
# Admin accounts are NEVER created via the public signup endpoint;
# they are provisioned only through the admin seeder (seed_admin.py).
ALLOWED_SIGNUP_ROLES = {RoleEnum.user, RoleEnum.company}


# ----------------------------
# Request Schemas
# ----------------------------

class SendOTPRequest(BaseModel):
    email: EmailStr


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: RoleEnum
    otp: str = ""
    phone: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ----------------------------
# Email Sending Function
# ----------------------------

def send_email_otp(receiver_email: str, otp: str):
    sender_email = os.getenv("EMAIL_ADDRESS")
    sender_password = os.getenv("EMAIL_PASSWORD")

    if not sender_email or not sender_password:
        logger.error(
            "OTP email failed: EMAIL_ADDRESS or EMAIL_PASSWORD is not set in .env "
            "(candidate signup OTP is required by default)."
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Email service is not configured and candidate signup OTP is "
                "required. Set EMAIL_ADDRESS and EMAIL_PASSWORD in .env (use a "
                "Gmail App Password), or for local development/testing only set "
                "BYPASS_EMAIL_OTP=true in .env to skip OTP."
            ),
        )

    subject = "RecruitO OTP Verification"
    body = f"Your OTP for RecruitO signup is: {otp}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email

    server = None
    try:
        logger.info("Connecting to %s:%s ...", SMTP_HOST, SMTP_PORT)
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        logger.info("OTP email sent to %s", receiver_email)
    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "SMTP authentication failed for %s — "
            "verify EMAIL_PASSWORD is a valid Gmail App Password "
            "(16-char, generated at myaccount.google.com/apppasswords). "
            "SMTP response: %s",
            sender_email,
            exc.smtp_code,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to send OTP email: SMTP authentication failed. Check EMAIL_PASSWORD (use a Gmail App Password, not your account password).",
        )
    except smtplib.SMTPConnectError as exc:
        logger.error("SMTP connection to %s:%s failed: %s", SMTP_HOST, SMTP_PORT, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to send OTP email: could not connect to SMTP server.",
        )
    except smtplib.SMTPException as exc:
        logger.error("SMTP error while sending OTP: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to send OTP email: SMTP error.",
        )
    except OSError as exc:
        logger.error("Network error while sending OTP (check internet/firewall): %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to send OTP email: network error.",
        )
    finally:
        if server is not None:
            try:
                server.quit()
            except smtplib.SMTPException:
                pass


# ----------------------------
# Send OTP Route
# ----------------------------

@router.post("/send-otp")
def send_otp(
    request: SendOTPRequest,
    raw_request: Request,
    db: Session = Depends(get_db),
):

    # Rate-limit OTP requests per IP + email to prevent abuse/spam.
    if RATE_LIMIT_ENABLED:
        check_rate_limit(
            f"otp:{client_ip(raw_request)}:{request.email.lower()}",
            OTP_MAX_REQUESTS,
            OTP_WINDOW_SECONDS,
            "Too many OTP requests. Please try again later.",
        )

    # Delete previous OTPs for this email
    db.query(EmailOTP).filter(EmailOTP.email == request.email).delete()

    # Generate 6-digit OTP
    otp = str(random.randint(100000, 999999))

    # Save OTP
    otp_entry = EmailOTP(
        email=request.email,
        otp=otp,
        created_at=datetime.utcnow()
    )

    db.add(otp_entry)
    db.commit()

    # Send email
    send_email_otp(request.email, otp)

    return {"message": "OTP sent successfully"}


# ----------------------------
# Resend OTP Route
# ----------------------------

@router.post("/resend-otp")
def resend_otp(request: SendOTPRequest, raw_request: Request, db: Session = Depends(get_db)):

    # Rate-limit OTP requests per IP + email to prevent spam/abuse.
    if RATE_LIMIT_ENABLED:
        check_rate_limit(
            f"otp:{client_ip(raw_request)}:{request.email.lower()}",
            OTP_MAX_REQUESTS,
            OTP_WINDOW_SECONDS,
            "Too many OTP requests. Please try again later.",
        )

    # Remove old OTPs
    db.query(EmailOTP).filter(EmailOTP.email == request.email).delete()

    # Generate new OTP
    otp = str(random.randint(100000, 999999))

    otp_entry = EmailOTP(
        email=request.email,
        otp=otp,
        created_at=datetime.utcnow()
    )

    db.add(otp_entry)
    db.commit()

    send_email_otp(request.email, otp)

    return {"message": "New OTP sent successfully"}


# ----------------------------
# Signup Route (with OTP verification)
# ----------------------------

@router.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):

    # Never trust the role coming from the client for privileged roles.
    # A caller cannot self-register as admin (or any future privileged role).
    if user.role not in ALLOWED_SIGNUP_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot be created via self signup"
        )

    # Check if email already exists
    existing_user = db.query(models.User).filter(
        models.User.email == user.email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    # Candidate role must be validated with OTP
    # TEMPORARY: when BYPASS_EMAIL_OTP is enabled the verification block below
    # is skipped so signup works without an email/OTP. Set BYPASS_EMAIL_OTP=false
    # to restore the original required-OTP flow.
    if user.role == RoleEnum.user and not BYPASS_EMAIL_OTP:
        # Get OTP record
        otp_record = db.query(EmailOTP).filter(
            EmailOTP.email == user.email,
            EmailOTP.otp == user.otp
        ).order_by(EmailOTP.id.desc()).first()

        if not otp_record:
            raise HTTPException(
                status_code=400,
                detail="Invalid OTP"
            )

        # Check OTP expiry (5 minutes)
        if datetime.utcnow() - otp_record.created_at > timedelta(minutes=5):
            db.delete(otp_record)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="OTP expired. Please request a new OTP."
            )

        # Delete OTP after successful use
        db.delete(otp_record)

    # Hash password
    try:
        hashed_password = hash_password(user.password)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Password too long"
        )

    # Create new user
    new_user = models.User(
        name=user.name,
        email=user.email,
        password=hashed_password,
        role=user.role,
        phone=user.phone,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "name": new_user.name,
        "email": new_user.email,
        "role": new_user.role
    }


# ----------------------------
# Login Route (Issues JWT with Role payload)
# ----------------------------

@router.post("/login")
def login(
    request: LoginRequest,
    raw_request: Request,
    db: Session = Depends(get_db),
):

    # Rate-limit login attempts per IP + email to thwart brute force.
    login_key = f"login:{client_ip(raw_request)}:{request.email.lower()}"
    if RATE_LIMIT_ENABLED:
        check_rate_limit(
            login_key,
            LOGIN_MAX_ATTEMPTS,
            LOGIN_WINDOW_SECONDS,
            "Too many login attempts. Please try again later.",
        )

    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or password"
        )

    if not verify_password(request.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or password"
        )

    # On successful login, clear the failed-attempts bucket for this caller.
    if RATE_LIMIT_ENABLED:
        reset_rate_limit(login_key)

    # Create access token including email (sub), id, and role in the payload
    access_token = create_access_token({
        "sub": user.email,
        "id": user.id,
        "role": user.role.value,
        "name": user.name
    })

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role.value,
        "name": user.name
    }


# ----------------------------
# Protected Profile / Dashboard Data (real, DB-backed)
# ----------------------------

@router.get("/api/user/profile")
def get_user_profile(
    current_user: models.User = Depends(RoleChecker(["user", "company", "admin"])),
    db: Session = Depends(get_db),
):
    return {
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "role": current_user.role.value,
            "phone": current_user.phone,
            "category": current_user.category,
            "skills": current_user.skills or [],
            "created_at": current_user.created_at,
        }
    }


@router.get("/api/company/data")
def get_company_data(
    current_user: models.User = Depends(RoleChecker(["company", "admin"])),
    db: Session = Depends(get_db),
):
    if current_user.role == models.RoleEnum.company:
        company = (
            db.query(models.Company)
            .filter(models.Company.user_id == current_user.id)
            .first()
        )
        if company is None:
            raise HTTPException(status_code=404, detail="Company profile not found")
        company_data = schemas.CompanyOut.model_validate(company)
        jobs = (
            db.query(models.Job)
            .filter(models.Job.company_id == company.id)
            .all()
        )
        applicants = (
            db.query(models.Application)
            .filter(models.Application.job_id.in_([j.id for j in jobs] or [0]))
            .count()
        )
        return {
            "company": company_data,
            "jobs_count": len(jobs),
            "applicants_count": applicants,
        }
    # Admin view: aggregate across all companies
    return {
        "total_companies": db.query(models.Company).count(),
        "total_jobs": db.query(models.Job).count(),
        "total_applications": db.query(models.Application).count(),
    }


@router.get("/api/admin/system-stats")
def get_admin_stats(
    current_user: models.User = Depends(RoleChecker(["admin"])),
    db: Session = Depends(get_db),
):
    return {
        "stats": {
            "total_users": db.query(models.User).count(),
            "total_companies": db.query(models.Company).count(),
            "total_jobs": db.query(models.Job).count(),
            "open_jobs": db.query(models.Job)
            .filter(models.Job.status == models.JobStatusEnum.open)
            .count(),
            "total_applications": db.query(models.Application).count(),
            "total_resumes": db.query(models.Resume).count(),
            "total_interviews": db.query(models.Interview).count(),
            "system_status": "healthy",
        }
    }
