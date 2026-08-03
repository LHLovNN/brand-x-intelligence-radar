from __future__ import annotations

from datetime import datetime, timedelta, timezone


UTC = timezone.utc
BEIJING = timezone(timedelta(hours=8))


def now_utc() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def from_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def beijing_daily_window(reference: datetime | None = None) -> tuple[datetime, datetime]:
    ref = reference or now_utc()
    bj = ref.astimezone(BEIJING)
    end_bj = bj.replace(hour=8, minute=0, second=0, microsecond=0)
    if bj < end_bj:
        end_bj = end_bj - timedelta(days=1)
    start_bj = end_bj - timedelta(days=1)
    return start_bj.astimezone(UTC), end_bj.astimezone(UTC)


def beijing_report_date_window(report_date: str) -> tuple[datetime, datetime]:
    if len(report_date) != 10:
        raise ValueError("report date must use YYYY-MM-DD")
    try:
        parsed = datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("report date must use YYYY-MM-DD") from error
    if parsed.strftime("%Y-%m-%d") != report_date:
        raise ValueError("report date must use YYYY-MM-DD")
    end_bj = parsed.replace(hour=8, minute=0, second=0, microsecond=0, tzinfo=BEIJING)
    start_bj = end_bj - timedelta(days=1)
    return start_bj.astimezone(UTC), end_bj.astimezone(UTC)


def beijing_label(value: datetime) -> str:
    return value.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M BJT")
