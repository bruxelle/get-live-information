from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import requests

from .models import XPost
from .state import SQLiteStateStore


logger = logging.getLogger(__name__)


@dataclass
class FetchMetadata:
    posts_fetched: int = 0
    estimated_post_read_count: int = 0
    rate_limit_headers: dict[str, str] = field(default_factory=dict)
    used_mock: bool = False


class PostFetcher(Protocol):
    last_fetch_metadata: FetchMetadata

    def fetch_recent_posts(self, *, since_id: str | None = None, max_results: int = 10) -> list[XPost]:
        ...


class XApiClient:
    base_url = "https://api.x.com/2"

    def __init__(
        self,
        bearer_token: str,
        username: str = "info_myojou",
        *,
        state: SQLiteStateStore | None = None,
        session: Any | None = None,
    ) -> None:
        self.bearer_token = bearer_token
        self.username = username
        self.state = state
        self.session = session or requests.Session()
        self.last_fetch_metadata = FetchMetadata()

    def fetch_recent_posts(self, *, since_id: str | None = None, max_results: int = 10) -> list[XPost]:
        user_id = self._get_user_id()
        params: dict[str, str | int] = {
            "max_results": max(5, min(max_results, 100)),
            "tweet.fields": "id,text,created_at,entities,attachments,referenced_tweets,note_tweet",
            "expansions": "attachments.media_keys",
            "media.fields": "media_key,type,url,preview_image_url,width,height,alt_text",
            "exclude": "retweets,replies",
        }
        if since_id:
            params["since_id"] = since_id
        response = self.session.get(
            f"{self.base_url}/users/{user_id}/tweets",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        posts = _posts_from_response_payload(payload)
        self.last_fetch_metadata = FetchMetadata(
            posts_fetched=len(posts),
            estimated_post_read_count=len(posts),
            rate_limit_headers=_rate_limit_headers(response.headers),
            used_mock=False,
        )
        logger.info(
            "X fetch complete: posts_fetched=%s estimated_post_reads=%s rate_limit=%s",
            len(posts),
            len(posts),
            self.last_fetch_metadata.rate_limit_headers or "{}",
        )
        return posts

    def _get_user_id(self) -> str:
        cached_user_id = self.state.get_cached_x_user_id(self.username) if self.state else None
        if cached_user_id:
            logger.info("Using cached X user_id for @%s.", self.username)
            return cached_user_id

        logger.info("Resolving X user_id for @%s; result will be cached.", self.username)
        response = self.session.get(
            f"{self.base_url}/users/by/username/{self.username}",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        user_id = payload["data"]["id"]
        if self.state:
            self.state.set_cached_x_user_id(self.username, user_id)
        lookup_headers = _rate_limit_headers(response.headers)
        if lookup_headers:
            logger.info("X username lookup rate_limit=%s", lookup_headers)
        return user_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}


class MockXClient:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.last_fetch_metadata = FetchMetadata(used_mock=True)

    def fetch_recent_posts(self, *, since_id: str | None = None, max_results: int = 10) -> list[XPost]:
        posts = self._load_posts()
        if since_id and since_id.isdigit():
            posts = [post for post in posts if post.id.isdigit() and int(post.id) > int(since_id)]
        posts.sort(key=lambda post: post.created_at, reverse=True)
        posts = posts[:max_results]
        self.last_fetch_metadata = FetchMetadata(
            posts_fetched=len(posts),
            estimated_post_read_count=0,
            used_mock=True,
        )
        return posts

    def _load_posts(self) -> list[XPost]:
        files = sorted(self.path.glob("*.json")) if self.path.is_dir() else [self.path]
        posts: list[XPost] = []
        for file_path in files:
            with file_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            items = payload.get("data", payload) if isinstance(payload, dict) else payload
            if isinstance(items, dict):
                items = [items]
            for item in items:
                posts.append(_post_from_payload(item))
        return posts


def _post_from_payload(item: dict) -> XPost:
    raw = _raw_post_payload(item)
    created_at = item.get("created_at") or raw.get("created_at") or item.get("source_posted_at") or raw.get("source_posted_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    api_text = _string_or_none(item.get("api_text") or raw.get("api_text") or raw.get("text") or item.get("text"))
    note_text = _note_tweet_text(raw)
    full_text_source = "note_tweet" if note_text else "text"
    full_text = note_text or str(item.get("text") or raw.get("text"))
    raw["api_text"] = api_text
    raw["truncated_text"] = api_text if full_text_source == "note_tweet" else None
    raw["full_text"] = full_text
    raw["full_text_source"] = full_text_source
    return XPost(
        id=str(item.get("id") or raw["id"]),
        text=full_text,
        created_at=created_at,
        raw=raw,
        api_text=api_text,
        truncated_text=api_text if full_text_source == "note_tweet" else None,
        full_text_source=full_text_source,
    )


def _posts_from_response_payload(payload: dict[str, Any]) -> list[XPost]:
    media_by_key = {
        str(media.get("media_key")): _media_metadata(media)
        for media in payload.get("includes", {}).get("media", [])
        if media.get("media_key")
    }
    posts: list[XPost] = []
    for item in payload.get("data", []):
        raw = dict(item)
        media_keys = raw.get("attachments", {}).get("media_keys", [])
        media = [media_by_key[key] for key in media_keys if key in media_by_key]
        if media:
            raw["media"] = media
        posts.append(_post_from_payload(raw))
    return posts


def _raw_post_payload(item: dict[str, Any]) -> dict[str, Any]:
    embedded_raw = item.get("raw")
    raw = dict(embedded_raw) if isinstance(embedded_raw, dict) else dict(item)
    for key in (
        "id",
        "text",
        "api_text",
        "truncated_text",
        "full_text",
        "full_text_source",
        "created_at",
        "url",
        "entities",
        "attachments",
        "referenced_tweets",
        "media",
        "note_tweet",
    ):
        if key in item and item[key] is not None:
            raw[key] = item[key]
    return raw


def _note_tweet_text(raw: dict[str, Any]) -> str | None:
    note_tweet = raw.get("note_tweet")
    if not isinstance(note_tweet, dict):
        return None
    return _string_or_none(note_tweet.get("text"))


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _media_metadata(media: dict[str, Any]) -> dict[str, Any]:
    fields = ("media_key", "type", "url", "preview_image_url", "width", "height", "alt_text")
    return {field: media[field] for field in fields if field in media}


def _rate_limit_headers(headers: Any) -> dict[str, str]:
    interesting = ("x-rate-limit-limit", "x-rate-limit-remaining", "x-rate-limit-reset")
    return {key: str(headers[key]) for key in interesting if key in headers}
