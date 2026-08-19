#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    ROOT / "public" / "index.html",
    ROOT / "public" / "dashboard-data-bundle.js",
    ROOT / "public" / "assets" / "app.js",
    ROOT / "public" / "assets" / "styles.css",
    ROOT / "public" / "dashboard-data" / "latest.json",
    ROOT / "public" / "dashboard-data" / "daily" / "latest.json",
    ROOT / "public" / "dashboard-data" / "daily" / "index.json",
    ROOT / "public" / "dashboard-data" / "fermentation.json",
    ROOT / "public" / "dashboard-data" / "competitor.json",
    ROOT / "public" / "dashboard-data" / "source-status.json",
    ROOT / "public" / "dashboard-data" / "run-status.json",
]

OPTIONAL = [
    ROOT / "public" / "dashboard-data" / "platform-trends" / "xiaohongshu" / "latest.json",
    ROOT / "public" / "dashboard-data" / "platform-trends" / "xiaohongshu" / "index.json",
    ROOT / "public" / "dashboard-data" / "dt-digests" / "index.json",
]


def main() -> None:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.exists()]
    if missing:
        print("Missing required files:")
        for item in missing:
            print(f"- {item}")
        sys.exit(1)
    optional_present = [path for path in OPTIONAL if path.exists()]
    if optional_present:
        print(f"Optional platform trend files present: {len(optional_present)}/{len(OPTIONAL)}")
    print("Dashboard files are present.")


if __name__ == "__main__":
    main()
