# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth import get_current_user
from app import models, schemas

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[schemas.NotificationOut])
def list_notifications(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The authenticated user's notifications, newest first."""
    return (
        db.query(models.Notification)
        .filter(models.Notification.user_id == current_user.id)
        .order_by(models.Notification.created_at.desc())
        .all()
    )


@router.get("/unread-count")
def unread_count(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == current_user.id,
            models.Notification.read == False,
        )
        .count()
    )
    return {"unread_count": count}


@router.post("/{notification_id}/read", response_model=schemas.NotificationOut)
def mark_read(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark one notification read. Scoped to the owner: another user's
    notification is indistinguishable from a missing one (404)."""
    notification = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == current_user.id,
            models.Notification.id == notification_id,
        )
        .first()
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not notification.read:
        notification.read = True
        db.commit()
        db.refresh(notification)
    return notification


@router.post("/read-all")
def mark_all_read(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark every unread notification of the current user as read."""
    notifications = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == current_user.id,
            models.Notification.read == False,
        )
        .all()
    )
    for notification in notifications:
        notification.read = True
    db.commit()
    return {
        "message": "All notifications marked as read",
        "marked": len(notifications),
    }