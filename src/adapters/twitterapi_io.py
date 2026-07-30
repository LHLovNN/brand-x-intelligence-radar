from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from src.adapters.x_source_base import ProviderBudgetExceeded, ProviderNotConfigured, XSourceBase
from src.utils.time import from_iso, now_utc, to_iso


class TwitterApiIoAdapter(XSourceBase):
    provider_name = "twitterapi_io"
    base_url = "https://api.twitterapi.io"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: int = 20,
        request_pause_seconds: float = 5.2,
        max_pages_per_query: int = 200,
        max_retries: int = 3,
        max_requests_per_run: int | None = None,
        max_context_requests_per_run: int | None = None,
    ) -> None:
        if not api_key:
            raise ProviderNotConfigured("TWITTERAPI_IO_KEY is required.")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.request_pause_seconds = request_pause_seconds
        self.max_pages_per_query = max_pages_per_query
        self.max_retries = max_retries
        self.max_requests_per_run = max_requests_per_run
        self.max_context_requests_per_run = max_context_requests_per_run
        self.requests_used = 0
        self.context_requests_used = 0
        self.request_budget_exhausted = False
        self.context_request_budget_exhausted = False
        self.last_request_at = 0.0

    def search_posts(
        self,
        query: str,
        start_time: str,
        end_time: str,
        limit: int,
        query_type: str = "Latest",
        budget_scope: str = "search",
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        query_type = self._normalized_query_type(query_type)
        bounded_query = self._with_time_window(query, start_time, end_time)
        posts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        pages = 0

        while len(posts) < limit and pages < self.max_pages_per_query:
            if cursor:
                if cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
            params = {
                "query": bounded_query,
                "queryType": query_type,
            }
            if cursor:
                params["cursor"] = cursor

            payload = self._get_json("/twitter/tweet/advanced_search", params, budget_scope=budget_scope)
            pages += 1
            rows = self._extract_tweets(payload)
            if not rows:
                break

            for row in rows:
                post = self._map_tweet(row, query, query_type=query_type)
                post_id = post["post_id"]
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)
                posts.append(post)
                if len(posts) >= limit:
                    break

            cursor = self._extract_next_cursor(payload)
            if not cursor:
                break
            time.sleep(self.request_pause_seconds)

        return posts

    def _normalized_query_type(self, query_type: str) -> str:
        value = str(query_type or "Latest").strip().lower()
        if value == "top":
            return "Top"
        return "Latest"

    def hydrate_posts(self, post_ids: list[str]) -> list[dict[str, Any]]:
        raise NotImplementedError("TwitterAPI.io hydration is not needed for the daily MVP path yet.")

    def conversation_posts(
        self,
        conversation_id: str,
        start_time: str,
        end_time: str,
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        query = f"conversation_id:{conversation_id}"
        return self.search_posts(query, start_time, end_time, limit, query_type="Latest", budget_scope="context")

    def _get_json(self, path: str, params: dict[str, str], budget_scope: str = "search") -> dict[str, Any]:
        query_string = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{self.base_url}{path}?{query_string}",
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "Joybuy-X-Intelligence-Radar/0.1",
            },
            method="GET",
        )
        body = ""
        for attempt in range(self.max_retries + 1):
            self._reserve_request_budget(budget_scope)
            self._wait_before_request()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if error.code == 429 and attempt < self.max_retries:
                    wait_seconds = self._retry_after_seconds(error) or max(5.5, self.request_pause_seconds)
                    print(
                        f"TwitterAPI.io free-tier rate limit hit; waiting {wait_seconds:.1f}s before retry.",
                        file=sys.stderr,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise RuntimeError(f"TwitterAPI.io request failed with HTTP {error.code}: {body[:300]}") from error
            except urllib.error.URLError as error:
                raise RuntimeError(f"TwitterAPI.io request failed: {error.reason}") from error

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"TwitterAPI.io returned non-JSON response: {body[:300]}") from error

        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(f"TwitterAPI.io returned error: {payload.get('error')}")
        return payload

    def _reserve_request_budget(self, budget_scope: str = "search") -> None:
        if budget_scope == "context":
            if self.max_context_requests_per_run is None:
                self.context_requests_used += 1
                return
            if self.context_requests_used >= self.max_context_requests_per_run:
                self.context_request_budget_exhausted = True
                raise ProviderBudgetExceeded(
                    f"TwitterAPI.io conversation context request budget exhausted: "
                    f"{self.context_requests_used}/{self.max_context_requests_per_run} requests used."
                )
            self.context_requests_used += 1
            return

        if self.max_requests_per_run is None:
            self.requests_used += 1
            return
        if self.requests_used >= self.max_requests_per_run:
            self.request_budget_exhausted = True
            raise ProviderBudgetExceeded(
                f"TwitterAPI.io request budget exhausted: "
                f"{self.requests_used}/{self.max_requests_per_run} requests used."
            )
        self.requests_used += 1

    def _wait_before_request(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        wait_seconds = self.request_pause_seconds - elapsed
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        self.last_request_at = time.monotonic()

    def _retry_after_seconds(self, error: urllib.error.HTTPError) -> float | None:
        value = error.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _with_time_window(self, query: str, start_time: str, end_time: str) -> str:
        start = self._parse_input_time(start_time)
        end = self._parse_input_time(end_time)
        if not start or not end:
            return query
        return f"{query} since_time:{int(start.timestamp())} until_time:{int(end.timestamp())}"

    def _parse_input_time(self, value: str) -> datetime | None:
        try:
            return from_iso(value)
        except ValueError:
            return None

    def _extract_tweets(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("tweets", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        nested = payload.get("result")
        if isinstance(nested, dict):
            return self._extract_tweets(nested)
        return []

    def _extract_next_cursor(self, payload: dict[str, Any]) -> str | None:
        for key in ("next_cursor", "nextCursor", "next", "cursor"):
            value = payload.get(key)
            if value:
                return str(value)
        nested = payload.get("pagination")
        if isinstance(nested, dict):
            for key in ("next_cursor", "nextCursor", "next", "cursor"):
                value = nested.get(key)
                if value:
                    return str(value)
        return None

    def _map_tweet(self, tweet: dict[str, Any], query: str, query_type: str = "Latest") -> dict[str, Any]:
        author = self._first_dict(tweet, "author", "user", "userInfo", "user_info") or {}
        post_id = self._string_value(tweet, "id", "tweet_id", "tweetId", "rest_id") or ""
        author_handle = self._string_value(author, "userName", "username", "screen_name", "handle") or ""
        url = self._string_value(tweet, "url", "tweet_url", "tweetUrl")
        if not url:
            if author_handle:
                url = f"https://x.com/{author_handle}/status/{post_id}"
            else:
                url = f"https://x.com/i/web/status/{post_id}"

        return {
            "post_id": post_id or url,
            "url": url,
            "text": self._string_value(tweet, "text", "full_text", "fullText", "content") or "",
            "author_id": self._string_value(author, "id", "user_id", "userId", "rest_id"),
            "author_name": self._string_value(author, "name", "display_name", "displayName") or author_handle,
            "author_handle": author_handle,
            "author_avatar_url": self._string_value(
                author,
                "profile_image_url",
                "profile_image_url_https",
                "profilePicture",
                "profilePictureUrl",
                "profileImageUrl",
                "avatar",
                "avatar_url",
            ),
            "author_followers": self._int_value(author, "followers", "followers_count", "followersCount"),
            "author_following": self._int_value(author, "following", "friends_count", "followingCount"),
            "author_bio": self._string_value(author, "description", "bio", "profileDescription"),
            "author_location": self._string_value(author, "location", "profileLocation", "userLocation"),
            "author_joined_at": self._normalized_time(
                self._first_value(author, "created_at", "createdAt", "created_time", "createdTime")
            ),
            "author_verified": self._bool_value(
                author,
                "verified",
                "isVerified",
                "isBlueVerified",
                "is_blue_verified",
                "blue",
                "verifiedType",
                "verified_type",
            ),
            "created_at": self._normalized_time(
                self._first_value(tweet, "created_at", "createdAt", "created_time", "createdTime", "timestamp")
            ),
            "collected_at": to_iso(now_utc()),
            "language": self._string_value(tweet, "lang", "language") or "und",
            "like_count": self._metric_value(tweet, "like_count", "likeCount", "favorite_count", "favoriteCount"),
            "repost_count": self._metric_value(
                tweet, "repost_count", "repostCount", "retweet_count", "retweetCount"
            ),
            "reply_count": self._metric_value(tweet, "reply_count", "replyCount"),
            "quote_count": self._metric_value(tweet, "quote_count", "quoteCount"),
            "bookmark_count": self._metric_value(tweet, "bookmark_count", "bookmarkCount", allow_none=True),
            "view_count": self._metric_value(tweet, "view_count", "viewCount", "views", allow_none=True),
            "media": self._media(tweet),
            "links": self._links(tweet),
            "quoted_post_id": self._nested_string(tweet, "quoted_tweet.id", "quotedTweet.id", "quoted_status_id_str"),
            "reply_to_post_id": self._string_value(
                tweet,
                "in_reply_to_status_id",
                "inReplyToStatusId",
                "in_reply_to_tweet_id",
                "replyToTweetId",
            ),
            "reply_to_handle": self._string_value(
                tweet,
                "in_reply_to_screen_name",
                "inReplyToScreenName",
                "replyToUser.username",
                "replyToUser.userName",
                "reply_to_user.username",
                "reply_to_user.userName",
            ),
            "conversation_id": self._string_value(tweet, "conversation_id", "conversationId"),
            "source_provider": self.provider_name,
            "query": query,
            "query_type": self._normalized_query_type(query_type),
            "brand_candidate": "",
        }

    def _metric_value(self, tweet: dict[str, Any], *keys: str, allow_none: bool = False) -> int | None:
        value = self._int_value(tweet, *keys, default=None)
        if value is None:
            metrics = self._first_dict(tweet, "public_metrics", "metrics", "counts") or {}
            value = self._int_value(metrics, *keys, default=None)
        if value is None and not allow_none:
            return 0
        return value

    def _links(self, tweet: dict[str, Any]) -> list[str]:
        links = self._list_value(tweet, "links", "entities.urls", "urls")
        values: list[str] = []
        for item in links:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                url = self._string_value(item, "expanded_url", "expandedUrl", "url")
                if url:
                    values.append(url)
        return values

    def _media(self, tweet: dict[str, Any]) -> list[Any]:
        media: list[Any] = []
        for key in (
            "media",
            "extended_entities.media",
            "extendedEntities.media",
            "entities.media",
            "attachments.media",
            "attachments.media_items",
            "photos",
            "images",
        ):
            for item in self._list_value(tweet, key):
                if item not in media:
                    media.append(item)
        for item in self._card_media(tweet):
            if item not in media:
                media.append(item)
        return media

    def _card_media(self, tweet: dict[str, Any]) -> list[dict[str, str]]:
        media: list[dict[str, str]] = []
        for key in ("card", "tweet_card", "tweetCard", "article", "articleData"):
            value = self._value(tweet, key)
            for url in self._image_urls(value):
                item = {"url": url, "type": "photo", "source": "card"}
                if item not in media:
                    media.append(item)
        return media

    def _image_urls(self, value: Any) -> list[str]:
        urls: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                key_hint = key.lower()
                if isinstance(child, str):
                    url = child.strip()
                    if self._looks_like_image_url(url, key_hint):
                        urls.append(url)
                else:
                    urls.extend(self._image_urls(child))
        elif isinstance(value, list):
            for child in value:
                urls.extend(self._image_urls(child))
        result: list[str] = []
        for url in urls:
            if url not in result:
                result.append(url)
        return result

    def _looks_like_image_url(self, url: str, key_hint: str = "") -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        lower = url.lower().split("?", 1)[0]
        if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            return True
        if "pbs.twimg.com/media/" in lower:
            return True
        return any(term in key_hint for term in ("image", "thumbnail", "photo", "picture"))

    def _normalized_time(self, value: Any) -> str:
        if value is None:
            return to_iso(now_utc())
        if isinstance(value, (int, float)):
            timestamp = value / 1000 if value > 10_000_000_000 else value
            return to_iso(datetime.fromtimestamp(timestamp, tz=timezone.utc))
        text = str(value).strip()
        if not text:
            return to_iso(now_utc())
        try:
            return to_iso(from_iso(text))
        except ValueError:
            pass
        try:
            return to_iso(parsedate_to_datetime(text).astimezone(timezone.utc))
        except (TypeError, ValueError, IndexError, OverflowError):
            return to_iso(now_utc())

    def _first_dict(self, source: dict[str, Any], *keys: str) -> dict[str, Any] | None:
        for key in keys:
            value = self._value(source, key)
            if isinstance(value, dict):
                return value
        return None

    def _first_value(self, source: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = self._value(source, key)
            if value is not None and value != "":
                return value
        return None

    def _list_value(self, source: dict[str, Any], *keys: str) -> list[Any]:
        for key in keys:
            value = self._value(source, key)
            if isinstance(value, list):
                return value
        return []

    def _nested_string(self, source: dict[str, Any], *keys: str) -> str | None:
        return self._string_value(source, *keys)

    def _string_value(self, source: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = self._value(source, key)
            if value is not None and value != "":
                return str(value)
        return None

    def _int_value(self, source: dict[str, Any], *keys: str, default: int | None = 0) -> int | None:
        for key in keys:
            value = self._value(source, key)
            if value is None or value == "":
                continue
            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue
        return default

    def _bool_value(self, source: dict[str, Any], *keys: str) -> bool:
        for key in keys:
            value = self._value(source, key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "blue", "business", "government"}
        return False

    def _value(self, source: dict[str, Any], key: str) -> Any:
        current: Any = source
        for part in key.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
