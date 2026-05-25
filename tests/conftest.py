from __future__ import annotations

from pathlib import Path

import pytest

from myojou_sync.models import XPost
from myojou_sync.x_client import MockXClient


@pytest.fixture
def mock_posts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "mock_posts"


@pytest.fixture
def mock_posts(mock_posts_dir: Path) -> dict[str, XPost]:
    client = MockXClient(mock_posts_dir)
    return {post.id: post for post in client.fetch_recent_posts(max_results=100)}
