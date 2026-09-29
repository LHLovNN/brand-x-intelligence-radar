#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.dashboard_builder import build_dashboard_data
from src.pipeline.platform_trends import write_platform_payload


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def daily_payload(date: str) -> dict:
    return {
        "platform": "xiaohongshu",
        "display_name": "Platform trends",
        "topic_label": "Growth methods",
        "date": date,
        "generated_at": f"{date}T01:00:00Z",
        "generated_at_label": date,
        "window_label": date,
        "items": [],
        "collection_status": {"status": "complete"},
        "summary": {"candidates_inspected": 0},
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="historical-pointers-") as temporary:
        target = Path(temporary) / "dashboard-data"
        build_dashboard_data([], [], str(target), report_date="2026-09-26", window_label="newer")
        build_dashboard_data([], [], str(target), report_date="2026-09-25", window_label="older")
        assert read(target / "daily" / "latest.json")["date"] == "2026-09-26"
        assert read(target / "daily" / "index.json")["latest_date"] == "2026-09-26"
        assert (target / "daily" / "2026-09-25.json").exists()

        write_platform_payload(target, daily_payload("2026-09-26"))
        write_platform_payload(target, daily_payload("2026-09-25"))
        platform = target / "platform-trends" / "xiaohongshu"
        assert read(platform / "latest.json")["date"] == "2026-09-26"
        assert read(platform / "index.json")["latest_date"] == "2026-09-26"
        assert (platform / "daily" / "2026-09-25.json").exists()

    print("Historical backfill pointer tests passed.")


if __name__ == "__main__":
    main()
