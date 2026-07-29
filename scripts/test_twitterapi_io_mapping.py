#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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

        def _get_json(self, path, params):
            self.requests.append({"path": path, "params": params})
            return {"tweets": []}

    capture = CaptureAdapter()
    capture.search_posts("joybuy", "2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z", 1, query_type="Top")
    assert capture.requests[0]["params"]["queryType"] == "Top"
    assert "since_time:" in capture.requests[0]["params"]["query"]
    assert "until_time:" in capture.requests[0]["params"]["query"]

    capped = TwitterApiIoAdapter(api_key="test-key", max_requests_per_run=0)
    try:
        capped.search_posts("joybuy", "2026-07-16T00:00:00Z", "2026-07-17T00:00:00Z", 1)
    except ProviderBudgetExceeded:
        pass
    else:
        raise AssertionError("expected ProviderBudgetExceeded when request cap is zero")
    assert capped.requests_used == 0
    assert capped.request_budget_exhausted is True
    print("TwitterAPI.io mapping test passed.")


if __name__ == "__main__":
    main()
