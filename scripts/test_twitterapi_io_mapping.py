#!/usr/bin/env python3
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.adapters import twitterapi_io as twitterapi_module
from src.adapters.twitterapi_io import ProviderBudgetExceeded, TwitterApiIoAdapter


def main() -> None:
    adapter = TwitterApiIoAdapter(api_key="test-key")
    sample = {
        "id": "1900000000000000001",
        "text": "Joybuy UK refund is still pending after a cancelled order.",
        "createdAt": "Fri Jul 17 01:15:00 +0000 2026",
        "lang": "en",
        "likeCount": 12,
        "retweetCount": 3,
        "replyCount": 4,
        "quoteCount": 1,
        "viewCount": 1200,
        "user": {
            "id": "user-1",
            "userName": "shopper_watch",
            "name": "Shopper Watch",
            "followers": 5000,
            "following": 212,
            "description": "Shopping deals and delivery watch.",
            "location": "London, UK",
            "createdAt": "Wed Oct 20 12:00:00 +0000 2010",
            "isVerified": True,
        },
        "replyToTweetId": "1899999999999999999",
        "inReplyToScreenName": "parent_author",
        "conversationId": "1899999999999999999",
        "entities": {
            "urls": [
                {
                    "url": "https://t.co/example",
                    "expanded_url": "https://example.com/case",
                }
            ],
            "media": [
                {
                    "media_url_https": "https://pbs.twimg.com/media/example-a.jpg",
                    "type": "photo",
                }
            ],
        },
        "extendedEntities": {
            "media": [
                {
                    "mediaUrlHttps": "https://pbs.twimg.com/media/example-b.jpg",
                    "type": "photo",
                }
            ]
        },
        "card": {
            "binding_values": [
                {
                    "key": "thumbnail_image_original",
                    "value": {
                        "image_value": {
                            "url": "https://example.com/card-preview.jpg",
                        }
                    },
                }
            ]
        },
    }

    mapped = adapter._map_tweet(sample, '"joybuy uk" refund -filter:retweets')
    assert mapped["post_id"] == sample["id"]
    assert mapped["author_handle"] == "shopper_watch"
    assert mapped["author_followers"] == 5000
    assert mapped["author_following"] == 212
    assert mapped["author_bio"] == "Shopping deals and delivery watch."
    assert mapped["author_location"] == "London, UK"
    assert mapped["author_joined_at"] == "2010-10-20T12:00:00Z"
    assert mapped["created_at"] == "2026-07-17T01:15:00Z"
    assert mapped["like_count"] == 12
    assert mapped["repost_count"] == 3
    assert mapped["reply_count"] == 4
    assert mapped["quote_count"] == 1
    assert mapped["view_count"] == 1200
    assert mapped["reply_to_post_id"] == "1899999999999999999"
    assert mapped["reply_to_handle"] == "parent_author"
    assert mapped["conversation_id"] == "1899999999999999999"
    assert mapped["links"] == ["https://example.com/case"]
    assert mapped["media"] == [
        {
            "mediaUrlHttps": "https://pbs.twimg.com/media/example-b.jpg",
            "type": "photo",
        },
        {
            "media_url_https": "https://pbs.twimg.com/media/example-a.jpg",
            "type": "photo",
        },
        {
            "url": "https://example.com/card-preview.jpg",
            "type": "photo",
            "source": "card",
        },
    ]
    assert mapped["query_type"] == "Latest"

    top_mapped = adapter._map_tweet(sample, '"joybuy uk" refund -filter:retweets', query_type="Top")
    assert top_mapped["query_type"] == "Top"

    class CaptureAdapter(TwitterApiIoAdapter):
        def __init__(self) -> None:
            super().__init__(api_key="test-key")
            self.requests = []

        def _get_json(self, path, params, budget_scope="search"):
            self._reserve_request_budget(budget_scope)
            self.requests.append({"path": path, "params": params, "budget_scope": budget_scope})
            return {"tweets": []}

    capture = CaptureAdapter()
    capture.search_posts("joybuy", "2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z", 1, query_type="Top")
    assert capture.requests[0]["params"]["queryType"] == "Top"
    assert capture.requests[0]["budget_scope"] == "search"
    assert "since_time:" in capture.requests[0]["params"]["query"]
    assert "until_time:" in capture.requests[0]["params"]["query"]
    capture.conversation_posts("1899999999999999999", "2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z", limit=1)
    assert capture.requests[1]["budget_scope"] == "context"
    assert capture.requests[1]["params"]["query"].startswith("conversation_id:1899999999999999999"), "conversation context should query by conversation_id"
    assert capture.requests_used == 1
    assert capture.context_requests_used == 1

    context_not_main_capped = CaptureAdapter()
    context_not_main_capped.max_requests_per_run = 0
    context_not_main_capped.conversation_posts(
        "1899999999999999999",
        "2026-07-16T00:00:00Z",
        "2026-07-17T00:00:00Z",
        limit=1,
    )
    assert context_not_main_capped.requests_used == 0, "conversation context should not consume search budget"
    assert context_not_main_capped.context_requests_used == 1

    thread_capture = CaptureAdapter()
    thread_payloads = [
        {
            "tweets": [
                {
                    **sample,
                    "id": "1899999999999999998",
                    "createdAt": "Thu Jul 16 23:59:00 +0000 2026",
                    "text": "Parent context before the collected reply.",
                }
            ],
            "has_next_page": True,
            "next_cursor": "cursor-2",
        },
        {
            "tweets": [
                {
                    **sample,
                    "id": "1900000000000000002",
                    "createdAt": "Fri Jul 17 00:30:00 +0000 2026",
                    "text": "Future context outside the report window.",
                },
                {
                    **sample,
                    "id": "1900000000000000001",
                    "createdAt": "Thu Jul 16 23:59:30 +0000 2026",
                    "text": "Collected reply.",
                },
            ],
            "has_next_page": False,
        },
    ]

    def thread_get_json(path, params, budget_scope="search"):
        thread_capture._reserve_request_budget(budget_scope)
        thread_capture.requests.append({"path": path, "params": params, "budget_scope": budget_scope})
        return thread_payloads.pop(0)

    thread_capture._get_json = thread_get_json
    thread_rows = thread_capture.thread_context_posts(
        "1900000000000000001",
        "2026-07-16T00:00:00Z",
        "2026-07-17T00:00:00Z",
        limit=10,
    )
    assert [row["post_id"] for row in thread_rows] == ["1899999999999999998", "1900000000000000001"]
    assert thread_capture.requests[0]["path"] == "/twitter/tweet/thread_context"
    assert thread_capture.requests[0]["params"]["tweetId"] == "1900000000000000001"
    assert thread_capture.requests[1]["params"]["cursor"] == "cursor-2"
    assert all(request["budget_scope"] == "context" for request in thread_capture.requests)

    capped = TwitterApiIoAdapter(api_key="test-key", max_requests_per_run=0)
    try:
        capped.search_posts("joybuy", "2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z", 1)
    except ProviderBudgetExceeded:
        pass
    else:
        raise AssertionError("expected ProviderBudgetExceeded when request cap is zero")
    assert capped.requests_used == 0
    assert capped.request_budget_exhausted is True

    class PaginatedBudgetAdapter(TwitterApiIoAdapter):
        def __init__(self) -> None:
            super().__init__(api_key="test-key", max_requests_per_run=2, request_pause_seconds=0)
            self.page = 0

        def _get_json(self, path, params, budget_scope="search"):
            self._reserve_request_budget(budget_scope)
            self.page += 1
            return {
                "tweets": [
                    {
                        **sample,
                        "id": str(1900000000000000100 + self.page),
                        "text": f"Joybuy page {self.page}",
                    }
                ],
                "next_cursor": f"cursor-{self.page + 1}",
            }

    partial = PaginatedBudgetAdapter()
    partial_rows = partial.search_posts("joybuy", "2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z", 5)
    assert [row["text"] for row in partial_rows] == ["Joybuy page 1", "Joybuy page 2"]
    assert partial.request_budget_exhausted is True

    class ScopedPaginationAdapter(TwitterApiIoAdapter):
        def __init__(self) -> None:
            super().__init__(
                api_key="test-key",
                max_pages_per_query=4,
                max_context_pages_per_query=2,
                request_pause_seconds=0,
            )
            self.page = 0
            self.requests = []

        def _get_json(self, path, params, budget_scope="search"):
            self._reserve_request_budget(budget_scope)
            self.page += 1
            self.requests.append({"path": path, "params": params, "budget_scope": budget_scope})
            return {
                "tweets": [
                    {
                        **sample,
                        "id": str(1900000000000000200 + self.page),
                        "createdAt": "Thu Jul 16 23:59:00 +0000 2026",
                        "text": f"{budget_scope} page {self.page}",
                    }
                ],
                "has_next_page": True,
                "next_cursor": f"cursor-{self.page + 1}",
            }

    scoped_search = ScopedPaginationAdapter()
    scoped_search_rows = scoped_search.search_posts(
        "joybuy",
        "2026-07-16T00:00:00Z",
        "2026-07-17T00:00:00Z",
        4,
    )
    assert len(scoped_search_rows) == 4, "normal search should still use the regular page cap"
    assert len(scoped_search.requests) == 4

    scoped_context = ScopedPaginationAdapter()
    scoped_context_rows = scoped_context.conversation_posts(
        "1899999999999999999",
        "2026-07-16T00:00:00Z",
        "2026-07-17T00:00:00Z",
        limit=5,
    )
    assert len(scoped_context_rows) == 2, "conversation context should stop at the context page cap"
    assert len(scoped_context.requests) == 2
    assert all(request["budget_scope"] == "context" for request in scoped_context.requests)

    scoped_thread = ScopedPaginationAdapter()
    scoped_thread_rows = scoped_thread.thread_context_posts(
        "1900000000000000001",
        "2026-07-16T00:00:00Z",
        "2026-07-17T00:00:00Z",
        limit=5,
    )
    assert len(scoped_thread_rows) == 2, "thread context should stop at the context page cap"
    assert len(scoped_thread.requests) == 2
    assert all(request["path"] == "/twitter/tweet/thread_context" for request in scoped_thread.requests)

    class FakeResponse:
        def __init__(self, body: str) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.body.encode("utf-8")

    original_urlopen = twitterapi_module.urllib.request.urlopen
    original_sleep = twitterapi_module.time.sleep
    try:
        timeout_calls = []
        waits = []

        def flaky_urlopen(request, timeout):
            timeout_calls.append(timeout)
            if len(timeout_calls) == 1:
                raise socket.timeout("simulated read timeout")
            return FakeResponse('{"tweets": []}')

        twitterapi_module.urllib.request.urlopen = flaky_urlopen
        twitterapi_module.time.sleep = waits.append
        retrying = TwitterApiIoAdapter(
            api_key="test-key",
            max_retries=1,
            request_pause_seconds=0.01,
            timeout_seconds=1,
        )
        assert retrying.search_posts("joybuy", "2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z", 1) == []
        assert len(timeout_calls) == 2
        assert any(wait >= 5.5 for wait in waits), "timeout retry should back off before retrying"

        timeout_calls.clear()

        def always_timeout(request, timeout):
            timeout_calls.append(timeout)
            raise socket.timeout("simulated read timeout")

        twitterapi_module.urllib.request.urlopen = always_timeout
        failing = TwitterApiIoAdapter(
            api_key="test-key",
            max_retries=0,
            request_pause_seconds=0.01,
            timeout_seconds=1,
        )
        try:
            failing.search_posts("joybuy", "2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z", 1)
        except RuntimeError as error:
            assert "timed out" in str(error)
        else:
            raise AssertionError("expected timeout to be wrapped as RuntimeError")
    finally:
        twitterapi_module.urllib.request.urlopen = original_urlopen
        twitterapi_module.time.sleep = original_sleep
    print("TwitterAPI.io mapping test passed.")


if __name__ == "__main__":
    main()
