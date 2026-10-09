#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_public_freshness import freshness_report
from scripts.check_diting_upstream import latest_upstream_dates, upstream_freshness_report
from scripts.verify_publication import observed_dates


def main() -> None:
    expected = "2026-09-15"
    current = {key: expected for key in ("brand", "xiaohongshu", "ai", "tg")}
    report = freshness_report(expected, current, {})
    assert report["fresh"] is True
    assert report["reachable"] is True

    stale = dict(current)
    stale["tg"] = "2026-09-14"
    report = freshness_report(expected, stale, {})
    assert report["fresh"] is False
    assert report["components"]["tg"]["fresh"] is False

    report = freshness_report(expected, current, {"diting": "network unavailable"})
    assert report["fresh"] is False
    assert report["reachable"] is False
    assert report["components"]["ai"]["error"] == "network unavailable"
    assert report["components"]["tg"]["error"] == "network unavailable"

    report = freshness_report(
        expected,
        current,
        {},
        {"xiaohongshu": {"healthy": False, "reason": "collection_status=partial, candidates_inspected=0"}},
    )
    assert report["reachable"] is True
    assert report["fresh"] is False
    assert report["components"]["xiaohongshu"]["fresh"] is False
    assert report["components"]["xiaohongshu"]["quality_reason"] == "collection_status=partial, candidates_inspected=0"

    report = freshness_report(
        expected,
        current,
        {},
        {"brand": {"healthy": False, "reason": "collection_status=partial"}},
    )
    assert report["fresh"] is False
    assert report["components"]["brand"]["fresh"] is False
    assert report["components"]["brand"]["quality_reason"] == "collection_status=partial"

    upstream_index = [
        {"f": "20260915-AI日报.html"},
        {"f": "2026-09-15-tg-digest.html"},
        {"f": "20260914-AI日报.html"},
    ]
    latest = latest_upstream_dates(upstream_index)
    assert latest == {"ai": "2026-09-15", "tg": "2026-09-15"}
    upstream = upstream_freshness_report(expected, latest)
    assert upstream["fresh"] is True

    upstream = upstream_freshness_report(expected, {"ai": expected, "tg": "2026-09-14"})
    assert upstream["fresh"] is False
    assert upstream["components"]["ai"]["fresh"] is True
    assert upstream["components"]["tg"]["fresh"] is False

    upstream = upstream_freshness_report(expected, {}, "network unavailable")
    assert upstream["reachable"] is False
    assert upstream["components"]["ai"]["error"] == "network unavailable"

    observed = observed_dates(
        {
            "brand_history": {"date": "2026-09-25"},
            "xiaohongshu_history": {"date": "2026-09-25"},
        },
        {"brand_history": "2026-09-25", "xiaohongshu_history": "2026-09-25"},
    )
    assert observed == {"brand_history": "2026-09-25", "xiaohongshu_history": "2026-09-25"}
    print("Public freshness tests passed.")


if __name__ == "__main__":
    main()
