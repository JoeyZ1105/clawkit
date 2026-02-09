import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import clawkit


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture(fixture_dir):
    def _loader(name: str) -> Any:
        with open(fixture_dir / name, "r", encoding="utf-8") as f:
            return json.load(f)
    return _loader


@pytest.fixture
def douyin_fixture(load_fixture):
    return load_fixture("douyin_result.json")


@pytest.fixture
def bilibili_fixture(load_fixture):
    return load_fixture("bilibili_result.json")


@pytest.fixture
def xhs_fixture(load_fixture):
    return load_fixture("xhs_result.json")


@pytest.fixture
def weibo_trending_fixture(load_fixture):
    return load_fixture("weibo_trending.json")


@pytest.fixture
def bilibili_trending_fixture(load_fixture):
    return load_fixture("bilibili_trending.json")


@pytest.fixture
def make_extract_result():
    def _make(data: dict) -> clawkit.ExtractResult:
        author = clawkit.Author(**data.get("author", {}))
        stats = clawkit.Stats(**data.get("stats", {}))
        media = [clawkit.MediaItem(**m) for m in data.get("media", [])]
        return clawkit.ExtractResult(
            platform=data.get("platform", ""),
            url=data.get("url", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            author=author,
            stats=stats,
            media=media,
            tags=data.get("tags", []),
            comments=[],
            raw_id=data.get("raw_id", ""),
            create_time=data.get("create_time", ""),
            duration=data.get("duration", 0),
            cover_url=data.get("cover_url", ""),
            avatar_url=data.get("avatar_url", ""),
            music=data.get("music", ""),
            location=data.get("location", ""),
            note_type=data.get("note_type", ""),
            pages=data.get("pages", []),
            quality_list=data.get("quality_list", []),
            related=data.get("related", []),
        )
    return _make


class MockHTTPXClient:
    def __init__(self, routes: dict[tuple[str, str], httpx.Response] | None = None):
        self.routes = routes or {}
        self.closed = False
        self.headers = {}
        self.cookies = httpx.Cookies()

    def request(self, method: str, url: str, **kwargs):
        key = (method.upper(), url)
        if key in self.routes:
            return self.routes[key]
        return httpx.Response(404, request=httpx.Request(method, url), json={})

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def close(self):
        self.closed = True


@pytest.fixture
def mock_httpx_client(monkeypatch):
    holder = {"instance": None}

    def _factory(routes=None):
        inst = MockHTTPXClient(routes=routes)
        holder["instance"] = inst
        monkeypatch.setattr(clawkit.httpx, "Client", lambda *a, **k: inst)
        return inst

    return _factory
