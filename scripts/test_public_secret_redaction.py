#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.io import PUBLIC_SECRET_REPLACEMENT, redact_public_secrets  # noqa: E402


def main() -> None:
    openai_like = "sk-" + "abcdefghijklmnopqrstuvwxyz"
    bearer_like = "Bearer " + "abcdefghijklmnopqrstuvwxyz1234"
    source = {
        "text": f"external post {openai_like}",
        "nested": [bearer_like, 7],
        "safe": "skill-name and ordinary public text",
    }
    redacted = redact_public_secrets(source)
    assert redacted["text"] == f"external post {PUBLIC_SECRET_REPLACEMENT}"
    assert redacted["nested"] == [PUBLIC_SECRET_REPLACEMENT, 7]
    assert redacted["safe"] == source["safe"]
    assert source["text"].startswith("external post " + "sk-")
    print("Public secret redaction tests passed.")


if __name__ == "__main__":
    main()
