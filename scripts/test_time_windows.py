#!/usr/bin/env python3
from datetime import datetime, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.time import beijing_daily_window, beijing_label, beijing_report_date_window, to_iso


def assert_report_window(report_date: str, expected_start: str, expected_end: str) -> None:
    start, end = beijing_report_date_window(report_date)
    assert to_iso(start) == expected_start
    assert to_iso(end) == expected_end
    assert beijing_label(end) == f"{report_date} 08:00 BJT"


def main() -> None:
    assert_report_window("2026-08-01", "2026-07-31T00:00:00Z", "2026-08-01T00:00:00Z")
    assert_report_window("2026-08-02", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")

    before_8_bjt = datetime(2026, 8, 2, 23, 59, tzinfo=timezone.utc)
    start, end = beijing_daily_window(before_8_bjt)
    assert to_iso(start) == "2026-08-01T00:00:00Z"
    assert to_iso(end) == "2026-08-02T00:00:00Z"

    after_8_bjt = datetime(2026, 8, 3, 0, 20, tzinfo=timezone.utc)
    start, end = beijing_daily_window(after_8_bjt)
    assert to_iso(start) == "2026-08-02T00:00:00Z"
    assert to_iso(end) == "2026-08-03T00:00:00Z"

    for invalid in ("2026-8-1", "2026-13-01", "2026/08/01"):
        try:
            beijing_report_date_window(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid report date to fail: {invalid}")

    print("Time window tests passed.")


if __name__ == "__main__":
    main()
