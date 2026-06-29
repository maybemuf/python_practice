from datetime import datetime, timezone


def ensure_utc(dt: datetime) -> datetime:
    """Гарантує timezone-aware datetime у UTC.

    Postgres (timestamptz) повертає aware-значення, а SQLite зберігає naive —
    тож при порівнянні з datetime.now(timezone.utc) трактуємо naive як UTC,
    щоб уникнути 'can't compare offset-naive and offset-aware datetimes'.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def validate_password(password: str) -> str:
    if not any(c.isupper() for c in password):
        raise ValueError("Password must contain an uppercase letter")
    if not any(c.islower() for c in password):
        raise ValueError("Password must contain a lowercase letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain a digit")
    return password