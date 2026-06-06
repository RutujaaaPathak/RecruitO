# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr
import random
import smtplib
import os
from email.mime.text import MIMEText
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from datetime import datetime, timedelta

from app.database import SessionLocal
from app import models
from app.utils import hash_password, verify_password
from app.models import RoleEnum, EmailOTP
from app.auth import create_access_token, get_current_user, RoleChecker

# Load .env variables
load_dotenv()

router = APIRouter()


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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str



# ----------------------------
# Database Dependency
# ----------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------
# Email Sending Function
# ----------------------------

def send_email_otp(receiver_email: str, otp: str):
    sender_email = os.getenv("EMAIL_ADDRESS")
    sender_password = os.getenv("EMAIL_PASSWORD")

    subject = "RecruitO OTP Verification"
    body = f"Your OTP for RecruitO signup is: {otp}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
    except Exception as e:
        print("Email sending failed:", e)
        raise HTTPException(status_code=500, detail="Failed to send OTP email")


# ----------------------------
# Send OTP Route
# ----------------------------

@router.post("/send-otp")
def send_otp(request: SendOTPRequest, db: Session = Depends(get_db)):

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
def resend_otp(request: SendOTPRequest, db: Session = Depends(get_db)):

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
    if user.role == RoleEnum.user:
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
        role=user.role
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
def login(request: LoginRequest, db: Session = Depends(get_db)):
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
# Protected Example Routes (RBAC Verification)
# ----------------------------

@router.get("/api/user/profile")
def get_user_profile(current_user: models.User = Depends(RoleChecker(["user", "company", "admin"]))):
    return {
        "message": "User profile accessed successfully",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "role": current_user.role.value
        }
    }


@router.get("/api/company/data")
def get_company_data(current_user: models.User = Depends(RoleChecker(["company", "admin"]))):
    return {
        "message": "Company secure dashboard data",
        "accessed_by": current_user.name
    }


@router.get("/api/admin/system-stats")
def get_admin_stats(current_user: models.User = Depends(RoleChecker(["admin"]))):
    return {
        "message": "Admin system-wide reports and metrics",
        "stats": {
            "users_online": 14,
            "system_status": "healthy"
        }
    }
