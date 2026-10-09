#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.query_builder import MAX_BASE_QUERY_LENGTH, build_x_search_queries


def main() -> None:
    terms = [f'long search term {index:02d}' for index in range(30)]
    context = [f'context term {index:02d}' for index in range(12)]
    config = {
        "brands": {
            "test": {
                "brand_terms": terms,
                "query_groups": [{"terms": terms, "context_terms": context}],
                "query_negative_terms": ["spam", "giveaway"],
            }
        }
    }
    queries = build_x_search_queries(config, "test")
    assert len(queries) > 1
    assert all(len(query) <= MAX_BASE_QUERY_LENGTH for query in queries)
    assert all("-filter:retweets" in query for query in queries)
    assert all("-spam" in query and "-giveaway" in query for query in queries)
    for term in terms:
        assert any(term in query for query in queries)
    for term in context:
        assert any(term in query for query in queries)
    print("Query builder tests passed.")


if __name__ == "__main__":
    main()
