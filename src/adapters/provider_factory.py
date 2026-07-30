from __future__ import annotations

import os

from src.adapters.sample import SampleXSource
from src.adapters.twitterapi_io import TwitterApiIoAdapter
from src.adapters.x_source_base import ProviderNotConfigured, XSourceBase


def optional_positive_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def optional_nonnegative_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def optional_positive_float_env(name: str) -> float | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def get_x_source(provider: str | None) -> XSourceBase:
    selected = (provider or "sample").strip().lower()
    if selected == "sample":
        return SampleXSource()
    if selected == "twitterapi_io":
        kwargs = {}
        timeout_seconds = optional_positive_int_env("TWITTERAPI_IO_TIMEOUT_SECONDS")
        request_pause_seconds = optional_positive_float_env("TWITTERAPI_IO_REQUEST_PAUSE_SECONDS")
        max_retries = optional_nonnegative_int_env("TWITTERAPI_IO_MAX_RETRIES")
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        if request_pause_seconds is not None:
            kwargs["request_pause_seconds"] = request_pause_seconds
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        return TwitterApiIoAdapter(api_key=os.getenv("TWITTERAPI_IO_KEY"), **kwargs)
    if selected in {"xpoz", "apify", "aisa_x"}:
        raise ProviderNotConfigured(
            f"{selected} adapter is reserved but not active in the sample MVP. "
            "Add the API key and implement the provider request mapping before enabling it."
        )
    raise ProviderNotConfigured(f"Unknown X source provider: {selected}")
