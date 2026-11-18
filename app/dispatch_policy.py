"""The automatic sender's daily allowance, measured in India time."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from app.models import DispatchAttempt, DispatchControl

INDIA = ZoneInfo("Asia/Kolkata")
DAILY_LIMIT = 5
START_HOUR = 9
MANAGED_PREFIX = "Target roles: batch "


def now():
    return datetime.now(timezone.utc)


def daily_start(at, offset_minutes=0):
    return (at.astimezone(INDIA).replace(hour=START_HOUR, minute=0, second=0, microsecond=0) + timedelta(minutes=offset_minutes)).astimezone(timezone.utc)


def budget(db, at=None):
    at = at or now()
    local = at.astimezone(INDIA)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(DispatchAttempt).where(
        DispatchAttempt.submission_started_at >= midnight.astimezone(timezone.utc),
        DispatchAttempt.submission_started_at < (midnight + timedelta(days=1)).astimezone(timezone.utc)))
    start = daily_start(at)
    remaining = max(0, DAILY_LIMIT - used)
    next_start = start if local < start else start + timedelta(days=1)
    return {"timezone": "Asia/Kolkata", "start_time": "09:00", "daily_limit": DAILY_LIMIT,
            "date": local.date().isoformat(), "used": used, "remaining": remaining,
            "window_open": local >= start, "can_send": local >= start and remaining > 0,
            "next_start_at": next_start.isoformat()}


def reserve_slot(db, attempt, at):
    """Caller commits this reservation and the durable sending state together."""
    control = db.get(DispatchControl, 1, with_for_update=True, populate_existing=True)
    if not control or not control.enabled or not budget(db, at)["can_send"]:
        return False
    if attempt.submission_started_at is not None:
        return False
    attempt.submission_started_at = at
    return True
