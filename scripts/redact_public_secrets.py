#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.io import redact_public_secrets, write_json  # noqa: E402


DATA_ROOT = ROOT / "public" / "dashboard-data"


def main() -> None:
    changed = 0
    for path in DATA_ROOT.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        redacted = redact_public_secrets(payload)
        if redacted == payload:
            continue
        write_json(str(path), redacted)
        changed += 1
    print(f"Redacted suspicious secret-like content in {changed} public JSON file(s).")


if __name__ == "__main__":
    main()
