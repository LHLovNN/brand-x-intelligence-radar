#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_BASE_URL = "https://lhlovnn.github.io/brand-x-intelligence-radar"
PUBLIC_PATHS = {
    "brand": "dashboard-data/daily/latest.json",
    "xiaohongshu": "dashboard-data/platform-trends/xiaohongshu/latest.json",
    "diting": "dashboard-data/dt-digests/index.json",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll published dashboard JSON until expected dates are visible.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--brand-date", default="")
    parser.add_argument("--xiaohongshu-date", default="")
    parser.add_argument("--ai-date", default="")
    parser.add_argument("--tg-date", default="")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    expected = {
        "brand": args.brand_date,
        "xiaohongshu": args.xiaohongshu_date,
        "ai": args.ai_date,
        "tg": args.tg_date,
    }
    expected = {key: value for key, value in expected.items() if value}
    if not expected:
        print("No publication dates requested; skipping public verification.")
        return

    deadline = time.monotonic() + max(1, args.timeout)
    last_seen: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            payloads = fetch_public_payloads(args.base_url, expected)
            last_seen = observed_dates(payloads, expected)
            if all(last_seen.get(key) == value for key, value in expected.items()):
                print("Published JSON verified: " + ", ".join(f"{key}={value}" for key, value in expected.items()))
                return
            last_error = ""
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError) as error:
            last_error = str(error)[:240]
        time.sleep(max(1, args.interval))

    details = ", ".join(f"{key}: expected {value}, saw {last_seen.get(key, 'unavailable')}" for key, value in expected.items())
    if last_error:
        details = f"{details}; last error: {last_error}"
    raise SystemExit(f"Published JSON did not become current before timeout: {details}")


def fetch_public_payloads(base_url: str, expected: dict[str, str]) -> dict[str, Any]:
    cache_bust = int(datetime.now(timezone.utc).timestamp() * 1000)
    payloads: dict[str, Any] = {}
    if "brand" in expected:
        payloads["brand"] = fetch_json(f"{base_url.rstrip('/')}/{PUBLIC_PATHS['brand']}?qa={cache_bust}")
    if "xiaohongshu" in expected:
        payloads["xiaohongshu"] = fetch_json(f"{base_url.rstrip('/')}/{PUBLIC_PATHS['xiaohongshu']}?qa={cache_bust}")
    if "ai" in expected or "tg" in expected:
        payloads["diting"] = fetch_json(f"{base_url.rstrip('/')}/{PUBLIC_PATHS['diting']}?qa={cache_bust}")
    return payloads


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "BrandRadarPublicationVerifier/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def observed_dates(payloads: dict[str, Any], expected: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    if "brand" in expected:
        result["brand"] = str(payloads.get("brand", {}).get("date") or "")
    if "xiaohongshu" in expected:
        result["xiaohongshu"] = str(payloads.get("xiaohongshu", {}).get("date") or "")
    if "ai" in expected:
        result["ai"] = str(payloads.get("diting", {}).get("latest", {}).get("ai") or "")
    if "tg" in expected:
        result["tg"] = str(payloads.get("diting", {}).get("latest", {}).get("tg") or "")
    return result


if __name__ == "__main__":
    main()
