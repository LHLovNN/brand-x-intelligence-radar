#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.adapters.x_source_base import ProviderBudgetExceeded
from scripts.run_daily import allocated_brand_request_limits, collect_real_posts


class PaginatedFakeSource:
    def __init__(self) -> None:
        self.max_requests_per_run = 6
        self.max_pages_per_query = 99
        self.requests_used = 0
        self.context_requests_used = 0
        self.max_context_requests_per_run = None
        self.request_budget_exhausted = False
        self.context_request_budget_exhausted = False
        self.calls: list[dict[str, Any]] = []

    def search_posts(
        self,
        query: str,
        start_time: str,
        end_time: str,
        limit: int,
        query_type: str = "Latest",
    ) -> list[dict[str, Any]]:
        page_cap = int(self.max_pages_per_query)
        self.calls.append({"query": query, "query_type": query_type, "limit": limit, "page_cap": page_cap})
        rows: list[dict[str, Any]] = []
        for page in range(page_cap):
            if self.requests_used >= self.max_requests_per_run:
                self.request_budget_exhausted = True
                if rows:
                    return rows
                raise ProviderBudgetExceeded(
                    f"TwitterAPI.io request budget exhausted: {self.requests_used}/{self.max_requests_per_run} requests used."
                )
            self.requests_used += 1
            for slot in range(20):
                if len(rows) >= limit:
                    return rows
                post_id = f"{len(self.calls)}-{page}-{slot}"
                rows.append(
                    {
                        "post_id": post_id,
                        "url": f"https://x.com/test/status/{post_id}",
                        "text": f"{query_type} result for {query}",
                        "created_at": "2026-09-01T00:00:00Z",
                        "language": "en",
                        "like_count": 1,
                        "repost_count": 0,
                        "reply_count": 0,
                        "quote_count": 0,
                        "bookmark_count": 0,
                        "view_count": 100,
                        "media": [],
                        "links": [],
                    }
                )
        return rows


def clear_collection_env() -> None:
    for name in [
        "BRAND_RADAR_PRIMARY_DAILY_LIMIT",
        "X_JOYBUY_DAILY_LIMIT",
        "BRAND_RADAR_COMPETITOR_DAILY_LIMIT",
        "X_TEMU_DAILY_LIMIT",
        "X_DAILY_LIMIT",
    ]:
        os.environ.pop(name, None)


def main() -> None:
    clear_collection_env()
    assert allocated_brand_request_limits(6, {"joybuy": 100, "temu": 20}) == {"joybuy": 5, "temu": 1}

    keyword_config = {
        "brands": {
            "joybuy": {
                "brand_terms": ["joybuy"],
                "query_groups": [
                    {"terms": ["joybuy"], "context_terms": []},
                    {"terms": ["jd.com"], "context_terms": []},
                ],
            },
            "temu": {
                "brand_terms": ["temu"],
                "query_context_terms": ["order"],
            },
        }
    }
    source_config = {
        "x_search_modes": [{"query_type": "Top", "ratio": 1}],
        "limits": {
            "max_posts_per_day": 120,
            "max_joybuy_posts_per_day": 100,
            "max_temu_posts_per_day": 20,
            "max_x_api_requests_per_run": 6,
        },
    }
    source = PaginatedFakeSource()
    posts, status = collect_real_posts(
        source,
        keyword_config,
        source_config,
        datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert status["limits"]["brand_request_limits"] == {"joybuy": 5, "temu": 1}
    assert [call["query_type"] for call in source.calls] == ["Top", "Top", "Top"]
    assert [call["page_cap"] for call in source.calls] == [3, 2, 1]
    assert [call["limit"] for call in source.calls] == [60, 40, 20]
    assert source.requests_used == 6
    brand_counts = {
        "joybuy": sum(1 for post in posts if post["brand_candidate"] == "joybuy"),
        "temu": sum(1 for post in posts if post["brand_candidate"] == "temu"),
    }
    assert brand_counts == {"joybuy": 100, "temu": 20}
    print("Collection budget tests passed.")


if __name__ == "__main__":
    main()
