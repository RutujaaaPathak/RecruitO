# pyrefly: ignore [missing-import]
from datetime import datetime

from app import models


def end_session(
    session: models.VideoInterview, now: datetime | None = None
) -> bool:
    """Mark the video interview session as completed (idempotent).

    Returns True when the session actually transitioned from in_progress to
    completed; False when it was already completed so callers never overwrite
    the original ``ended_at``.
    """
    if session.status != models.AssessmentStatusEnum.in_progress:
        return False
    session.status = models.AssessmentStatusEnum.completed
    session.ended_at = now or datetime.utcnow()
    return True


def apply_device_state(
    session: models.VideoInterview,
    camera_enabled: bool,
    microphone_enabled: bool,
) -> None:
    """Persist the candidate's current camera/microphone toggle state.

    Mirrors the device state synced from the room so a resumed session can
    restart with the same toggles.
    """
    session.camera_enabled = bool(camera_enabled)
    session.microphone_enabled = bool(microphone_enabled)


def session_duration_seconds(
    session: models.VideoInterview, now: datetime | None = None
) -> int:
    """Elapsed time of the session in whole seconds.

    For a live session this grows until ended_at is set; for a completed
    session it is the final duration.
    """
    endpoint = session.ended_at or now or datetime.utcnow()
    delta = endpoint - session.started_at
    return max(0, int(delta.total_seconds()))