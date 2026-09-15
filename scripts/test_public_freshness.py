#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_public_freshness import freshness_report


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
    print("Public freshness tests passed.")


if __name__ == "__main__":
    main()
