import json
import re
from pathlib import Path
from typing import Any


PUBLIC_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY-----"),
)
PUBLIC_SECRET_REPLACEMENT = "[REDACTED_SECRET]"


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: str, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_public_dashboard_path(target):
        data = redact_public_secrets(data)
    with open(target, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_jsonl(path: str, rows: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False))
            file.write("\n")


def is_public_dashboard_path(path: Path) -> bool:
    normalized = path.resolve().as_posix()
    return "/public/dashboard-data/" in normalized


def redact_public_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_public_secrets(child) for key, child in value.items()}
    if isinstance(value, list):
        return [redact_public_secrets(child) for child in value]
    if isinstance(value, str):
        redacted = value
        for pattern in PUBLIC_SECRET_PATTERNS:
            redacted = pattern.sub(PUBLIC_SECRET_REPLACEMENT, redacted)
        return redacted
    return value

