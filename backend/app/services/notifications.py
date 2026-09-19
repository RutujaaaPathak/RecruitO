"""Notification service: create persistent in-app notifications.

Route handlers own the transaction: call ``create_notification`` right before
their existing ``db.commit()`` so the notification and the triggering change
commit atomically (roll back together on failure).
"""
from app import models


def create_notification(
    db,
    user_id: int,
    *,
    type: models.NotificationType,
    title: str,
    message: str,
    link: str | None = None,
) -> models.Notification:
    """Queue (without committing) a notification for a single user."""
    notification = models.Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        link=link,
    )
    db.add(notification)
    return notification