#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_publication import DEFAULT_BASE_URL, PUBLIC_PATHS, fetch_json


def observed_component_dates(base_url: str) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, Any]]]:
    cache_bust = int(datetime.now().timestamp() * 1000)
    dates: dict[str, str] = {}
    errors: dict[str, str] = {}
    quality: dict[str, dict[str, Any]] = {}
    targets = {
        "brand": PUBLIC_PATHS["brand"],
        "xiaohongshu": PUBLIC_PATHS["xiaohongshu"],
        "diting": PUBLIC_PATHS["diting"],
    }
    payloads: dict[str, Any] = {}
    for key, path in targets.items():
        try:
            payloads[key] = fetch_json(f"{base_url.rstrip('/')}/{path}?health={cache_bust}")
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError) as error:
            errors[key] = str(error)[:240]
    dates["brand"] = str(payloads.get("brand", {}).get("date") or "")
    dates["xiaohongshu"] = str(payloads.get("xiaohongshu", {}).get("date") or "")
    dates["ai"] = str(payloads.get("diting", {}).get("latest", {}).get("ai") or "")
    dates["tg"] = str(payloads.get("diting", {}).get("latest", {}).get("tg") or "")
    brand_status = (payloads.get("brand", {}).get("collection_status") or {})
    brand_collection_state = str(brand_status.get("status") or "")
    quality["brand"] = {
        "healthy": brand_collection_state in {"complete", "sample"},
        "reason": (
            ""
            if brand_collection_state in {"complete", "sample"}
            else f"collection_status={brand_collection_state or 'missing'}"
        ),
    }
    xiaohongshu_status = (payloads.get("xiaohongshu", {}).get("collection_status") or {})
    candidates = int(xiaohongshu_status.get("candidates_inspected") or 0)
    collection_state = str(xiaohongshu_status.get("status") or "")
    quality["xiaohongshu"] = {
        "healthy": collection_state == "complete" and candidates > 0,
        "reason": (
            ""
            if collection_state == "complete" and candidates > 0
            else f"collection_status={collection_state or 'missing'}, candidates_inspected={candidates}"
        ),
    }
    return dates, errors, quality


def freshness_report(
    expected_date: str,
    dates: dict[str, str],
    errors: dict[str, str],
    quality: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    quality = quality or {}
    components = {}
    for key in ("brand", "xiaohongshu", "ai", "tg"):
        observed = dates.get(key, "")
        quality_result = quality.get(key) or {"healthy": True, "reason": ""}
        components[key] = {
            "expected": expected_date,
            "observed": observed,
            "fresh": observed == expected_date and bool(quality_result.get("healthy", True)),
            "quality_healthy": bool(quality_result.get("healthy", True)),
            "quality_reason": str(quality_result.get("reason") or ""),
            "error": errors.get("diting" if key in {"ai", "tg"} else key, ""),
        }
    return {
        "expected_date": expected_date,
        "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "reachable": not errors,
        "fresh": not errors and all(item["fresh"] for item in components.values()),
        "components": components,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether all public dashboard modules expose the expected date.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--expected-date", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    dates, errors, quality = observed_component_dates(args.base_url)
    report = freshness_report(args.expected_date, dates, errors, quality)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered + "\n", encoding="utf-8")
        temporary.replace(args.output)
    print(rendered)
    if errors:
        raise SystemExit(2)
    if not report["fresh"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
