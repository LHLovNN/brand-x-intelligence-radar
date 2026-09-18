#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sync_dt_digests import DEFAULT_BASE_URL, digest_kind_and_date


def latest_upstream_dates(search_index: list[dict[str, Any]]) -> dict[str, str]:
    latest = {"ai": "", "tg": ""}
    for item in search_index:
        kind, date = digest_kind_and_date(str(item.get("f") or ""))
        if kind and date and date > latest[kind]:
            latest[kind] = date
    return latest


def upstream_freshness_report(
    expected_date: str,
    latest: dict[str, str],
    error: str = "",
) -> dict[str, Any]:
    components = {
        kind: {
            "expected": expected_date,
            "observed": str(latest.get(kind) or ""),
            "fresh": not error and str(latest.get(kind) or "") == expected_date,
            "error": error,
        }
        for kind in ("ai", "tg")
    }
    return {
        "expected_date": expected_date,
        "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "reachable": not error,
        "fresh": not error and all(item["fresh"] for item in components.values()),
        "components": components,
    }


def fetch_search_index(base_url: str) -> list[dict[str, Any]]:
    cache_bust = int(datetime.now().timestamp() * 1000)
    url = f"{base_url.rstrip('/')}/search-index.json?health={cache_bust}"
    request = urllib.request.Request(url, headers={"User-Agent": "BrandRadarHealthCheck/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("upstream search index is not a list")
    return payload


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(rendered + "\n", encoding="utf-8")
        temporary.replace(path)
    print(rendered)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether the upstream AI/TG source has today's digests.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--expected-date", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    error = ""
    latest = {"ai": "", "tg": ""}
    try:
        latest = latest_upstream_dates(fetch_search_index(args.base_url))
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        error = str(exc)[:240]

    report = upstream_freshness_report(args.expected_date, latest, error)
    write_report(args.output, report)
    if error:
        raise SystemExit(2)
    if not report["fresh"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
