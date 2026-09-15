#!/usr/bin/env python3
from __future__ import annotations

import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_daily import parse_args, read_collection_checkpoint


def parsed(*args: str):
    with patch.object(sys, "argv", ["run_daily.py", *args]):
        return parse_args()


def rejected(*args: str) -> None:
    with redirect_stderr(StringIO()):
        try:
            parsed(*args)
        except SystemExit as error:
            assert error.code == 2
        else:
            raise AssertionError(f"Expected invalid arguments to be rejected: {args}")


def main() -> None:
    args = parsed(
        "--resume-from-checkpoint",
        "--checkpoint-date",
        "2026-09-15",
        "--refresh-platform-trends",
        "--platform-trends-only",
    )
    assert args.resume_from_checkpoint
    assert args.refresh_platform_trends
    assert args.platform_trends_only
    assert args.checkpoint_date == "2026-09-15"

    rejected("--checkpoint-date", "2026-09-15")
    rejected("--refresh-platform-trends")
    rejected("--resume-from-checkpoint", "--platform-trends-only")
    rejected(
        "--resume-from-checkpoint",
        "--refresh-platform-trends",
        "--platform-trends-only",
        "--attach-context-from-provider",
    )

    checkpoint_path = ROOT / "data" / "checkpoints" / "daily" / "2026-09-15.json"
    if checkpoint_path.exists():
        checkpoint = read_collection_checkpoint("2026-09-15")
        assert checkpoint["report_date"] == "2026-09-15"
    print("Daily mode tests passed.")


if __name__ == "__main__":
    main()
