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
            "tweet.fields": "created_at,entities",
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
        posts = [_post_from_payload(item) for item in payload.get("data", [])]
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
    created_at = item.get("created_at") or item.get("source_posted_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return XPost(
        id=str(item["id"]),
        text=item["text"],
        created_at=created_at,
        raw=item,
    )


def _rate_limit_headers(headers: Any) -> dict[str, str]:
    interesting = ("x-rate-limit-limit", "x-rate-limit-remaining", "x-rate-limit-reset")
    return {key: str(headers[key]) for key in interesting if key in headers}
