from datetime import UTC, datetime


def ensure_utc(dt: datetime) -> datetime:
    """Guarantees a timezone-aware datetime in UTC.

    Postgres (timestamptz) returns aware values while SQLite stores naive ones —
    so when comparing against datetime.now(timezone.utc) we treat naive as UTC
    to avoid 'can't compare offset-naive and offset-aware datetimes'.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def validate_password(password: str) -> str:
    if not any(c.isupper() for c in password):
        raise ValueError("Password must contain an uppercase letter")
    if not any(c.islower() for c in password):
        raise ValueError("Password must contain a lowercase letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain a digit")
    return password