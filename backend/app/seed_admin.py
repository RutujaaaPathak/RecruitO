import os
# pyrefly: ignore [missing-import]
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app import models
from app.utils import hash_password

def seed_admin():
    """Create a default admin account if it does not exist.

    The admin credentials are read from environment variables:
        ADMIN_EMAIL
        ADMIN_PASSWORD
    If those are not set, the script prints a warning and aborts.
    """
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        print("[WARN] ADMIN_EMAIL and ADMIN_PASSWORD must be set in the environment.")
        return
    db = SessionLocal()
    try:
        existing = db.query(models.User).filter(models.User.email == admin_email).first()
        if existing:
            print(f"[INFO] Admin user already exists (id={existing.id}).")
            return
        hashed = hash_password(admin_password)
        admin_user = models.User(
            name="admin",
            email=admin_email,
            password=hashed,
            role=models.RoleEnum.admin,
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        print(f"[OK] Created admin user id={admin_user.id}.")
    except IntegrityError as e:
        db.rollback()
        print(f"[ERROR] Could not create admin user: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_admin()
