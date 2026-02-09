#!/usr/bin/env python3
# /// script
# dependencies = ["httpx"]
# ///
"""
ClawKit v3.2 - 社交媒体内容提取工具

免费、本地运行、无需 API key。
支持平台: 抖音、小红书、B站、微博、快手、知乎、YouTube、Twitter/X、闲鱼

用法:
    uv run clawkit.py "链接"
    uv run clawkit.py "链接" --action download --output ./media
    uv run clawkit.py "链接" --json
    uv run clawkit.py "链接" --comments
    uv run clawkit.py --batch links.txt --json --output results/
    uv run clawkit.py --search "关键词" --platform goofish
    uv run clawkit.py --trending douyin        # 抖音热搜
    uv run clawkit.py --trending bilibili      # B站热门
    uv run clawkit.py --trending weibo         # 微博热搜
    uv run clawkit.py --trending zhihu         # 知乎热榜
"""

import re
import os
import sys
import json
import html
import time
import hashlib
import logging
import argparse
import subprocess
import atexit
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, unquote
from pathlib import Path

import httpx

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("clawkit")
__version__ = "3.3.0"

# ─── 签名引擎（可选） ─────────────────────────────────────────────────────────
try:
    from .sign_engine import sign_douyin, sign_xiaohongshu, get_xhs_cookies, get_xhs_search_id
    HAS_SIGN_ENGINE = True
    logger.debug("签名引擎已加载")
except ImportError:
    HAS_SIGN_ENGINE = False
    logger.debug("签名引擎不可用，使用无签名方案")

# ─── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class Author:
    nickname: str = ""
    uid: str = ""
    sec_uid: str = ""
    bio: str = ""
    followers: int = 0
    following: int = 0
    total_likes: int = 0
    works_count: int = 0

@dataclass
class Stats:
    likes: int = 0
    comments: int = 0
    shares: int = 0
    collects: int = 0
    views: int = 0
    danmaku: int = 0
    coins: int = 0
    reposts: int = 0

@dataclass
class MediaItem:
    url: str = ""
    type: str = "video"  # video / image
    width: int = 0
    height: int = 0

@dataclass
class Comment:
    author: str = ""
    avatar: str = ""
    content: str = ""
    likes: int = 0
    time: str = ""
    replies: list = field(default_factory=list)
    ip_location: str = ""

@dataclass
class ExtractResult:
    platform: str = ""
    url: str = ""
    title: str = ""
    description: str = ""
    full_text: str = ""  # OCR text + description merged
    analysis: dict = field(default_factory=dict)  # LLM analysis result
    author: Author = field(default_factory=Author)
    stats: Stats = field(default_factory=Stats)
    media: list[MediaItem] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    raw_id: str = ""
    create_time: str = ""
    duration: int = 0
    cover_url: str = ""
    avatar_url: str = ""
    music: str = ""
    location: str = ""
    is_ad: bool = False
    note_type: str = ""  # "image" / "video" / ""
    pages: list[dict] = field(default_factory=list)  # multi-P for bilibili
    quality_list: list[dict] = field(default_factory=list)  # available qualities
    related: list[dict] = field(default_factory=list)  # related videos

    def to_dict(self) -> dict:
        return asdict(self)

# ─── HTTP 工具 ──────────────────────────────────────────────────────────────────

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

TIMEOUT = float(os.getenv("CLAWKIT_TIMEOUT", "15.0"))
MAX_RETRIES = 3

NETWORK_EXCEPTIONS = (
    httpx.HTTPError,
    httpx.TimeoutException,
)

PARSE_EXCEPTIONS = (
    json.JSONDecodeError,
    ValueError,
    IndexError,
    TypeError,
)

# Backward compatibility for internal references.
HANDLED_EXCEPTIONS = NETWORK_EXCEPTIONS + PARSE_EXCEPTIONS

API_ENDPOINTS = {
    "douyin": {
        "user_info": "https://www.iesdouyin.com/web/api/v2/user/info/?sec_uid={sec_uid}",
        "share_video": "https://www.iesdouyin.com/share/video/{video_id}",
        "hotsearch": "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/",
        "hotsearch_fallback": "https://www.douyin.com/aweme/v1/web/hot/search/list/",
    },
    "bilibili": {
        "view": "https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
        "popular": "https://api.bilibili.com/x/web-interface/popular?ps=20&pn=1",
    },
    "twitter": {
        "fxtwitter_status": "https://api.fxtwitter.com/{url_path}",
        "fxtwitter_user": "https://api.fxtwitter.com/{screen_name}",
        "syndication": "https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=x",
    },
}

_cookie_cache: dict[str, dict[str, str]] = {}
_client_pool: dict[tuple[str, bool], httpx.Client] = {}
_last_request: dict[str, float] = {}
_trending_cache: dict[str, tuple[float, list]] = {}

def _load_cookies() -> dict[str, dict]:
    """Load cookies from ~/.clawkit/cookies.json if exists."""
    cookie_path = Path.home() / ".clawkit" / "cookies.json"
    if cookie_path.exists():
        try:
            with open(cookie_path) as f:
                return json.load(f)
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"Failed to load cookies: {e}")
    return {}

_cookies_store = _load_cookies()

def _get_cookies(platform: str) -> dict[str, str]:
    """Get cookies for a platform. Supports both formats:
    - Simple: {"weibo": {"SUB": "xxx"}}
    - Auth.py: {"weibo": {"cookies": {"SUB": "xxx"}, "updated_at": "..."}}
    """
    if platform in _cookie_cache:
        return _cookie_cache[platform]
    entry = _cookies_store.get(platform, {})
    if isinstance(entry, dict) and "cookies" in entry and isinstance(entry.get("cookies"), dict):
        cookies = entry["cookies"]
    else:
        cookies = entry if isinstance(entry, dict) else {}
    _cookie_cache[platform] = cookies
    return cookies


def _headers(mobile: bool = True, platform: str = "") -> dict[str, str]:
    return {
        "User-Agent": MOBILE_UA if mobile else DESKTOP_UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _get_client(platform: str = "", mobile: bool = True) -> httpx.Client:
    key = (platform, mobile)
    if key not in _client_pool:
        _client_pool[key] = httpx.Client(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers=_headers(mobile, platform),
            cookies=_get_cookies(platform) or None,
        )
    return _client_pool[key]


def _close_clients() -> None:
    for c in _client_pool.values():
        c.close()


atexit.register(_close_clients)


def _client(mobile: bool = True, platform: str = "") -> httpx.Client:
    return _get_client(platform=platform, mobile=mobile)


def _release_client(client: httpx.Client) -> None:
    """Release a client instance.

    - Pooled clients are managed globally and must stay open until atexit.
    - Ad-hoc clients (created directly via httpx.Client) should be closed here.
    """
    if client not in _client_pool.values():
        try:
            client.close()
        except HANDLED_EXCEPTIONS:
            pass


def _rate_limit(platform: str, min_interval: float = 0.5) -> None:
    now = _time.time()
    last = _last_request.get(platform, 0)
    wait = max(0, min_interval - (now - last))
    if wait > 0:
        _time.sleep(wait)
    _last_request[platform] = _time.time()


def _cached_trending(platform: str, fetch_fn) -> list:
    now = time.time()
    if platform in _trending_cache:
        ts, data = _trending_cache[platform]
        if now - ts < 300:
            return data
    data = fetch_fn()
    _trending_cache[platform] = (now, data)
    return data

def _request_with_retry(client: httpx.Client, method: str, url: str, platform: str = "", **kwargs) -> httpx.Response:
    """HTTP request with exponential backoff retry."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            _rate_limit(platform or urlparse(url).netloc)
            resp = client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning(f"Retry {attempt+1}/{MAX_RETRIES} for {url}: {e}")
            time.sleep(wait)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited, waiting {wait}s")
                time.sleep(wait)
                last_exc = e
            else:
                raise
    raise last_exc or Exception(f"Request failed after {MAX_RETRIES} retries")

# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _safe_int(v) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        v = v.replace(",", "").replace("+", "").strip()
        if "亿" in v:
            v = v.replace("亿", "")
            try:
                return int(float(v) * 100000000)
            except ValueError:
                return 0
        if "万" in v:
            v = v.replace("万", "")
            try:
                return int(float(v) * 10000)
            except ValueError:
                return 0
        try:
            return int(float(v))
        except ValueError:
            return 0
    return 0

def _fmt_num(n: int) -> str:
    if n >= 100000000:
        return f"{n/100000000:.1f}亿"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)

def _ts_to_iso(ts) -> str:
    """Convert Unix timestamp to ISO string."""
    try:
        ts = int(ts)
        if ts > 0:
            return datetime.fromtimestamp(ts).isoformat()
    except (ValueError, TypeError, OSError):
        pass
    return ""

# ─── 平台识别 ──────────────────────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    if not isinstance(url, str) or not url.strip() or not url.startswith(("http://", "https://")):
        raise ValueError(f"无效URL: {url}")
    u = url.lower()
    if any(k in u for k in ["douyin.com", "iesdouyin.com"]):
        return "douyin"
    if any(k in u for k in ["xiaohongshu.com", "xhslink.com", "xhs.cn"]):
        return "xiaohongshu"
    if any(k in u for k in ["bilibili.com", "b23.tv"]):
        return "bilibili"
    if any(k in u for k in ["weibo.com", "weibo.cn"]):
        return "weibo"
    if any(k in u for k in ["kuaishou.com", "gifshow.com"]):
        return "kuaishou"
    if any(k in u for k in ["zhihu.com"]):
        return "zhihu"
    if any(k in u for k in ["youtube.com", "youtu.be"]):
        return "youtube"
    if any(k in u for k in ["twitter.com", "x.com", "nitter"]):
        return "twitter"
    if any(k in u for k in ["goofish.com", "xianyu.com", "2.taobao.com/item"]):
        return "goofish"
    raise ValueError(f"无法识别平台: {url}")

# ─── 基类 ──────────────────────────────────────────────────────────────────────

class BaseExtractor(ABC):
    """Base class for all platform extractors."""

    platform: str = ""

    @abstractmethod
    def extract(self, url: str) -> ExtractResult:
        ...

    def fetch_comments(self, content_id: str, cursor: int = 0, count: int = 20) -> list[Comment]:
        """Override in subclasses that support comments."""
        return []

    def trending(self) -> list[dict]:
        """获取平台热门/趋势内容。返回 list[dict]，每个 dict 含 title, url, hot_value, rank。"""
        raise NotImplementedError(f"{self.platform} 暂不支持热门内容获取")

# ─── 抖音 ──────────────────────────────────────────────────────────────────────

class DouyinExtractor(BaseExtractor):
    platform = "douyin"

    def _fetch_user_info(self, client: httpx.Client, sec_uid: str) -> dict:
        api = API_ENDPOINTS["douyin"]["user_info"].format(sec_uid=sec_uid)
        resp = _request_with_retry(client, "GET", api, platform=self.platform)
        data = resp.json()
        return data.get("user_info", {}) if isinstance(data, dict) else {}

    def extract_user(self, url_or_sec_uid: str) -> dict:
        """Extract user profile info from douyin user page or sec_uid."""
        client = _client(mobile=True, platform="douyin")
        try:
            sec_uid = url_or_sec_uid
            if "douyin.com" in url_or_sec_uid:
                resp = _request_with_retry(client, "GET", url_or_sec_uid)
                final = str(resp.url)
                m = re.search(r'sec_uid=([^&]+)', final) or re.search(r'/user/([^?/]+)', final)
                if m:
                    sec_uid = m.group(1)
                else:
                    # Try from page
                    m = re.search(r'"secUid"\s*:\s*"([^"]+)"', resp.text)
                    if m:
                        sec_uid = m.group(1)

            info = self._fetch_user_info(client, sec_uid)
            return {
                "platform": "douyin",
                "type": "user_profile",
                "nickname": info.get("nickname", ""),
                "sec_uid": sec_uid,
                "uid": info.get("uid", ""),
                "short_id": info.get("short_id", ""),
                "bio": info.get("signature", ""),
                "avatar": info.get("avatar_larger", {}).get("url_list", [""])[0],
                "followers": _safe_int(info.get("mplatform_followers_count", 0)) or _safe_int(info.get("follower_count", 0)),
                "following": _safe_int(info.get("following_count", 0)),
                "total_likes": _safe_int(info.get("total_favorited", 0)),
                "works_count": _safe_int(info.get("aweme_count", 0)),
                "verified": info.get("custom_verify", ""),
            }
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"抖音用户信息获取失败: {e}")
            return {"error": str(e)}
        finally:
            _release_client(client)

    def search(self, keyword: str, count: int = 10) -> dict:
        """Search douyin videos by keyword. Requires sign_engine for a_bogus."""
        if not HAS_SIGN_ENGINE:
            return {
                "platform": "douyin", "type": "search", "status": "no_sign_engine",
                "message": "抖音搜索需要签名引擎（sign_engine.py），请确保它在同目录下。",
                "keyword": keyword,
            }
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        client = httpx.Client(headers={"User-Agent": ua, "Referer": "https://www.douyin.com/"}, follow_redirects=True, timeout=15)
        try:
            params = f"keyword={keyword}&search_channel=aweme_video_web&sort_type=0&publish_time=0&offset=0&count={count}&aid=6383&cookie_enabled=true&platform=PC&downlink=10"
            a_bogus = sign_douyin(params, ua)
            url = f"https://www.douyin.com/aweme/v1/web/general/search/single/?{params}&a_bogus={a_bogus}"
            resp = client.get(url)
            data = resp.json()
            results = []
            for item in (data.get("data", []) or []):
                aweme = item.get("aweme_info", {})
                if not aweme:
                    continue
                desc = aweme.get("desc", "")
                author = aweme.get("author", {})
                stats = aweme.get("statistics", {})
                results.append({
                    "title": desc,
                    "author": author.get("nickname", ""),
                    "aweme_id": aweme.get("aweme_id", ""),
                    "url": f"https://www.douyin.com/video/{aweme.get('aweme_id', '')}",
                    "likes": _safe_int(stats.get("digg_count", 0)),
                    "comments": _safe_int(stats.get("comment_count", 0)),
                    "shares": _safe_int(stats.get("share_count", 0)),
                    "plays": _safe_int(stats.get("play_count", 0)),
                })
            return {
                "platform": "douyin", "type": "search", "keyword": keyword,
                "count": len(results), "results": results,
            }
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"抖音搜索失败: {e}")
            return {"platform": "douyin", "type": "search", "error": str(e), "keyword": keyword}
        finally:
            _release_client(client)

    def extract(self, url: str) -> ExtractResult:
        client = _client(mobile=True, platform="douyin")

        # Resolve short link → get video_id
        resp = _request_with_retry(client, "GET", url)
        final_url = str(resp.url)
        video_id = final_url.split("?")[0].strip("/").split("/")[-1]

        # Fetch share page
        share_url = API_ENDPOINTS["douyin"]["share_video"].format(video_id=video_id)
        resp = _request_with_retry(client, "GET", share_url)

        m = re.search(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", resp.text, re.DOTALL)
        if not m:
            raise ValueError("抖音: 无法从页面提取数据")

        router = json.loads(m.group(1).strip())
        if not isinstance(router, dict):
            raise ValueError("抖音: router 数据格式异常")
        loader = router.get("loaderData", {})
        if not isinstance(loader, dict):
            raise ValueError("抖音: loaderData 数据格式异常")

        page_data = None
        for key in loader:
            if "page" in key:
                page_data = loader[key]
                break
        if not page_data:
            raise ValueError("抖音: 无法定位视频数据")

        video_info_res = page_data.get("videoInfoRes", {})
        item_list = video_info_res.get("item_list", [])
        if not item_list:
            raise ValueError("抖音: item_list 为空")
        item = item_list[0]

        # Video URL
        video_url = ""
        try:
            video_url = item["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        except (KeyError, IndexError):
            logger.warning("抖音: 无法获取视频 URL")

        # Author
        a = item.get("author", {})
        sec_uid = a.get("sec_uid", "")
        author = Author(
            nickname=a.get("nickname", ""),
            uid=a.get("uid", "") or a.get("short_id", "") or str(a.get("id", "")),
            sec_uid=sec_uid,
        )
        avatar_url = a.get("avatar_thumb", {}).get("url_list", [""])[0] if a.get("avatar_thumb") else ""

        # Fetch author details via user info API
        if sec_uid:
            try:
                user_info = self._fetch_user_info(client, sec_uid)
                if user_info:
                    author.bio = user_info.get("signature", "")
                    author.followers = _safe_int(user_info.get("mplatform_followers_count", 0)) or _safe_int(user_info.get("follower_count", 0))
                    author.following = _safe_int(user_info.get("following_count", 0))
                    author.total_likes = _safe_int(user_info.get("total_favorited", 0))
                    author.works_count = _safe_int(user_info.get("aweme_count", 0))
                    if not avatar_url:
                        avatar_url = user_info.get("avatar_larger", {}).get("url_list", [""])[0]
            except HANDLED_EXCEPTIONS as e:
                logger.warning(f"抖音: 作者详情获取失败: {e}")

        # Stats
        stats_raw = item.get("statistics", {})
        play_count = stats_raw.get("play_count", 0)
        # If play_count is 0, try other fields
        if not play_count:
            play_count = stats_raw.get("play_count_str", 0)
            if isinstance(play_count, str):
                play_count = _safe_int(play_count)

        stats = Stats(
            likes=_safe_int(stats_raw.get("digg_count", 0)),
            comments=_safe_int(stats_raw.get("comment_count", 0)),
            shares=_safe_int(stats_raw.get("share_count", 0)),
            collects=_safe_int(stats_raw.get("collect_count", 0)),
            views=_safe_int(play_count),
        )

        # Description & tags
        desc = item.get("desc", "")
        tags = re.findall(r"#([\w\u4e00-\u9fff]+)", desc)

        # Create time
        create_time = _ts_to_iso(item.get("create_time", 0))

        # Duration (in seconds, video.duration is in ms)
        duration = 0
        try:
            duration = int(item.get("video", {}).get("duration", 0)) // 1000
        except (ValueError, TypeError):
            pass
        if not duration:
            try:
                duration = int(item.get("duration", 0)) // 1000
            except (ValueError, TypeError):
                pass

        # Cover
        cover_url = ""
        try:
            cover_url = item["video"]["cover"]["url_list"][0]
        except (KeyError, IndexError):
            try:
                cover_url = item["video"]["origin_cover"]["url_list"][0]
            except (KeyError, IndexError):
                pass

        # Music
        music = ""
        music_info = item.get("music", {})
        if music_info:
            music = music_info.get("title", "")
            music_author = music_info.get("author", "")
            if music_author and music_author != music:
                music = f"{music} - {music_author}"

        # Location
        location = ""
        poi_info = item.get("poi_info", {})
        if poi_info:
            location = poi_info.get("poi_name", "")

        # Is ad
        is_ad = bool(item.get("is_ads", False))

        # Media
        media = []
        images = item.get("images")
        if images:
            for img in images:
                img_url = img.get("url_list", [""])[0]
                if img_url:
                    media.append(MediaItem(url=img_url, type="image",
                                           width=img.get("width", 0),
                                           height=img.get("height", 0)))
        elif video_url:
            w = item.get("video", {}).get("width", 0)
            h = item.get("video", {}).get("height", 0)
            media.append(MediaItem(url=video_url, type="video", width=w, height=h))

        _release_client(client)
        return ExtractResult(
            platform="douyin",
            url=url,
            title=desc,
            description=desc,
            author=author,
            stats=stats,
            media=media,
            tags=tags,
            raw_id=video_id,
            create_time=create_time,
            duration=duration,
            cover_url=cover_url,
            avatar_url=avatar_url,
            music=music,
            location=location,
            is_ad=is_ad,
        )

    def fetch_comments(self, video_id: str, cursor: int = 0, count: int = 20, max_pages: int = 1) -> list[Comment]:
        """Fetch comments with cursor-based pagination. max_pages up to 5 (100 comments)."""
        client = _client(mobile=True, platform="douyin")
        all_comments = []
        cur = cursor
        max_pages = min(max_pages, 5)
        try:
            for page in range(max_pages):
                api = f"https://www.iesdouyin.com/web/api/v2/comment/list/?aweme_id={video_id}&cursor={cur}&count=20"
                resp = _request_with_retry(client, "GET", api)
                data = resp.json()
                page_comments = data.get("comments", [])
                if not page_comments:
                    break
                for c in page_comments:
                    replies = []
                    for r in (c.get("reply_comment", []) or []):
                        replies.append(Comment(
                            author=r.get("user", {}).get("nickname", ""),
                            avatar=r.get("user", {}).get("avatar_thumb", {}).get("url_list", [""])[0] if r.get("user", {}).get("avatar_thumb") else "",
                            content=r.get("text", ""),
                            likes=_safe_int(r.get("digg_count", 0)),
                            time=_ts_to_iso(r.get("create_time", 0)),
                            ip_location=r.get("ip_label", ""),
                        ))
                    all_comments.append(Comment(
                        author=c.get("user", {}).get("nickname", ""),
                        avatar=c.get("user", {}).get("avatar_thumb", {}).get("url_list", [""])[0] if c.get("user", {}).get("avatar_thumb") else "",
                        content=c.get("text", ""),
                        likes=_safe_int(c.get("digg_count", 0)),
                        time=_ts_to_iso(c.get("create_time", 0)),
                        replies=replies,
                        ip_location=c.get("ip_label", ""),
                    ))
                if len(all_comments) >= count:
                    break
                # cursor for next page
                cur = data.get("cursor", 0)
                has_more = data.get("has_more", False)
                if not has_more or not cur:
                    break
                time.sleep(0.5)  # rate limit
            return all_comments[:count]
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"抖音评论获取失败: {e}")
            return all_comments  # return what we got
        finally:
            _release_client(client)

    def fetch_related(self, video_id: str) -> list[dict]:
        """Try to extract related videos from share page."""
        client = _client(mobile=True, platform="douyin")
        try:
            share_url = API_ENDPOINTS["douyin"]["share_video"].format(video_id=video_id)
            resp = _request_with_retry(client, "GET", share_url)
            m = re.search(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", resp.text, re.DOTALL)
            if not m:
                return []
            router = json.loads(m.group(1).strip())
            loader = router.get("loaderData", {})
            related = []
            for key in loader:
                if "page" in key:
                    page_data = loader[key]
                    # Look for related/recommend items
                    for rkey in ["relatedVideoRes", "recommendList", "related_item_list"]:
                        items = page_data.get(rkey, {})
                        if isinstance(items, dict):
                            items = items.get("item_list", []) or items.get("aweme_list", [])
                        if isinstance(items, list):
                            for item in items[:10]:
                                related.append({
                                    "id": item.get("aweme_id", ""),
                                    "desc": item.get("desc", ""),
                                    "author": item.get("author", {}).get("nickname", ""),
                                    "likes": _safe_int(item.get("statistics", {}).get("digg_count", 0)),
                                })
            return related
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"抖音相关推荐获取失败: {e}")
            return []
        finally:
            _release_client(client)

    def trending(self) -> list[dict]:
        """获取抖音热搜榜。"""
        client = _client(mobile=False, platform="douyin")
        try:
            resp = _request_with_retry(client, "GET",
                API_ENDPOINTS["douyin"]["hotsearch"])
            data = resp.json()
            word_list = data.get("word_list", [])
            results = []
            for i, item in enumerate(word_list, 1):
                results.append({
                    "rank": i,
                    "title": item.get("word", ""),
                    "url": f"https://www.douyin.com/search/{item.get('word', '')}",
                    "hot_value": _safe_int(item.get("hot_value", 0)),
                })
            return results
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"抖音热搜获取失败: {e}")
            # Fallback: try douyin trending API
            try:
                resp = _request_with_retry(client, "GET",
                    API_ENDPOINTS["douyin"]["hotsearch_fallback"])
                data = resp.json()
                word_list = data.get("data", {}).get("word_list", [])
                results = []
                for i, item in enumerate(word_list, 1):
                    results.append({
                        "rank": i,
                        "title": item.get("word", ""),
                        "url": f"https://www.douyin.com/search/{item.get('word', '')}",
                        "hot_value": _safe_int(item.get("hot_value", 0)),
                    })
                return results
            except HANDLED_EXCEPTIONS as e2:
                raise RuntimeError(f"抖音热搜获取失败: {e}; fallback also failed: {e2}")
        finally:
            _release_client(client)

# ─── 小红书 ────────────────────────────────────────────────────────────────────

class XiaohongshuExtractor(BaseExtractor):
    platform = "xiaohongshu"

    def extract(self, url: str) -> ExtractResult:
        client = _client(mobile=True, platform="xiaohongshu")
        resp = _request_with_retry(client, "GET", url)
        page = resp.text

        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>", page, re.DOTALL)
        if not m:
            raise ValueError("小红书: 无法从页面提取数据")

        raw = m.group(1).strip().replace("undefined", "null")
        state = json.loads(raw)

        note_data = None
        # Mobile structure
        nd_root = state.get("noteData", {}).get("data", {})
        if nd_root:
            note_data = nd_root.get("noteData", {})
        # Desktop structure
        if not note_data:
            ndm = state.get("note", {}).get("noteDetailMap", {})
            if ndm:
                first_key = next(iter(ndm))
                note_data = ndm[first_key].get("note", {})
        if not note_data:
            raise ValueError("小红书: 无法定位笔记数据")

        title = note_data.get("title", "")
        desc = note_data.get("desc", "")
        interact = note_data.get("interactInfo", {})
        user = note_data.get("user", {})

        author = Author(
            nickname=user.get("nickName", "") or user.get("nickname", ""),
            uid=user.get("userId", ""),
            bio=user.get("desc", "") or user.get("signature", ""),
            followers=_safe_int(user.get("fansCount", 0) or user.get("fans", 0)),
            following=_safe_int(user.get("follows", 0) or user.get("followCount", 0)),
            total_likes=_safe_int(user.get("likedCount", 0) or user.get("liked", 0)),
        )
        avatar_url = user.get("avatar", "")

        stats = Stats(
            likes=_safe_int(interact.get("likedCount", "0")),
            collects=_safe_int(interact.get("collectedCount", "0")),
            comments=_safe_int(interact.get("commentCount", "0")),
            shares=_safe_int(interact.get("shareCount", "0")),
        )

        # Create time
        create_time = ""
        for time_key in ["time", "noteTime", "createTime"]:
            ct = note_data.get(time_key, "")
            if ct:
                if isinstance(ct, (int, float)) or (isinstance(ct, str) and ct.isdigit()):
                    ts = int(ct)
                    # XHS sometimes uses milliseconds
                    if ts > 1e12:
                        ts = ts // 1000
                    create_time = _ts_to_iso(ts)
                else:
                    create_time = str(ct)
                if create_time:
                    break

        # Media - images
        media = []
        image_list = note_data.get("imageList", [])
        for img in image_list:
            info_list = img.get("infoList", [])
            # Pick highest resolution: sort by width descending
            best = {}
            if info_list:
                best = max(info_list, key=lambda x: x.get("width", 0) or 0)
            img_url = best.get("url", img.get("url", ""))
            if img_url:
                if not img_url.startswith("http"):
                    img_url = "https:" + img_url
                elif img_url.startswith("http://"):
                    img_url = img_url.replace("http://", "https://", 1)
                media.append(MediaItem(
                    url=img_url, type="image",
                    width=img.get("width", 0),
                    height=img.get("height", 0),
                ))

        # Media - video
        video_info = note_data.get("video", {})
        v_url = ""
        media_info = video_info.get("media", {})
        if media_info:
            stream = media_info.get("stream", {})
            for codec in ["h264", "h265", "av1"]:
                streams = stream.get(codec, [])
                if streams:
                    v_url = streams[0].get("masterUrl", "")
                    if v_url:
                        break
        if not v_url:
            v_url = video_info.get("url", "")
        if v_url:
            if not v_url.startswith("http"):
                v_url = "https:" + v_url
            media.append(MediaItem(url=v_url, type="video"))

        # Duration
        duration = 0
        if video_info:
            try:
                duration = int(video_info.get("duration", 0))
            except (ValueError, TypeError):
                pass

        # Cover
        cover_url = ""
        if video_info:
            cover_url = video_info.get("thumbnail", {}).get("url", "") or video_info.get("cover", {}).get("url", "")
        if not cover_url and image_list:
            # First image as cover
            first_img = image_list[0]
            il = first_img.get("infoList", [])
            if il:
                cover_url = il[0].get("url", "")

        # Determine note type (after media parsing)
        note_type = ""
        if note_data.get("type") == "video" or video_info:
            note_type = "video"
        elif image_list:
            note_type = "image"

        tags = [t["name"] for t in note_data.get("tagList", []) if t.get("name")]
        if not tags:
            text = f"{title}\n{desc}".strip()
            tags = re.findall(r"#([\w\u4e00-\u9fff]+)", text)

        note_id = note_data.get("noteId", "")

        # Comments from page JSON
        comments = self._extract_page_comments(state)

        _release_client(client)
        return ExtractResult(
            platform="xiaohongshu",
            url=url,
            title=title,
            description=desc,
            author=author,
            stats=stats,
            media=media,
            tags=tags,
            comments=comments,
            raw_id=note_id,
            create_time=create_time,
            duration=duration,
            cover_url=cover_url,
            avatar_url=avatar_url,
            note_type=note_type,
        )

    def _extract_page_comments(self, state: dict) -> list[Comment]:
        """Try multiple paths to extract comments from page JSON."""
        comments = []
        comment_data = None

        # Path 1: state.comment.comments
        try:
            comment_data = state.get("comment", {}).get("comments", [])
        except HANDLED_EXCEPTIONS:
            pass

        # Path 2: state.noteData.data.comments
        if not comment_data:
            try:
                comment_data = state.get("noteData", {}).get("data", {}).get("comments", [])
            except HANDLED_EXCEPTIONS:
                pass

        # Path 3: state.note.noteDetailMap.*.comments
        if not comment_data:
            try:
                ndm = state.get("note", {}).get("noteDetailMap", {})
                if ndm:
                    first_key = next(iter(ndm))
                    comment_data = ndm[first_key].get("comments", [])
            except HANDLED_EXCEPTIONS:
                pass

        if not comment_data:
            return []

        for c in (comment_data or [])[:20]:
            try:
                user_info = c.get("userInfo", {}) or c.get("user", {})
                replies = []
                sub_comments = c.get("subComments", []) or c.get("subCommentList", []) or []
                for sc in sub_comments[:5]:
                    sc_user = sc.get("userInfo", {}) or sc.get("user", {})
                    replies.append(Comment(
                        author=sc_user.get("nickName", "") or sc_user.get("nickname", ""),
                        content=sc.get("content", ""),
                        likes=_safe_int(sc.get("likeCount", 0)),
                    ))
                comments.append(Comment(
                    author=user_info.get("nickName", "") or user_info.get("nickname", ""),
                    content=c.get("content", ""),
                    likes=_safe_int(c.get("likeCount", 0)),
                    time=c.get("createTime", ""),
                    replies=replies,
                    ip_location=c.get("ipLocation", ""),
                ))
            except HANDLED_EXCEPTIONS as e:
                logger.warning(f"小红书评论解析失败: {e}")
        return comments

    def fetch_comments(self, note_id: str, cursor: int = 0, count: int = 20) -> list[Comment]:
        """Fetch XHS comments via API with signing."""
        if not HAS_SIGN_ENGINE:
            logger.warning("小红书评论API需要签名引擎（sign_engine.py）")
            return []
        a1, web_id = get_xhs_cookies()
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        uri = "/api/sns/web/v2/comment/page"
        params = {"note_id": note_id, "cursor": str(cursor), "top_comment_id": "", "image_formats": "jpg,webp,avif"}
        sign_headers = sign_xiaohongshu(uri, data=None, a1=a1)
        client = httpx.Client(
            headers={"User-Agent": ua, "Referer": "https://www.xiaohongshu.com/", "Origin": "https://www.xiaohongshu.com",
                     "x-s": sign_headers["x-s"], "x-t": sign_headers["x-t"], "x-s-common": sign_headers["x-s-common"]},
            cookies={"a1": a1, "webId": web_id}, follow_redirects=True, timeout=15)
        try:
            resp = client.get(f"https://edith.xiaohongshu.com{uri}", params=params)
            data = resp.json()
            comments = []
            for c in (data.get("data", {}).get("comments", []) or []):
                replies = []
                for r in (c.get("sub_comments", []) or []):
                    replies.append(Comment(
                        author=r.get("user_info", {}).get("nickname", ""),
                        content=r.get("content", ""),
                        likes=_safe_int(r.get("like_count", 0)),
                        time=_ts_to_iso(r.get("create_time", 0)),
                    ))
                comments.append(Comment(
                    author=c.get("user_info", {}).get("nickname", ""),
                    content=c.get("content", ""),
                    likes=_safe_int(c.get("like_count", 0)),
                    time=_ts_to_iso(c.get("create_time", 0)),
                    replies=replies,
                ))
            return comments[:count]
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"小红书评论获取失败: {e}")
            return []
        finally:
            _release_client(client)

    def trending(self) -> list[dict]:
        """获取小红书热门话题。"""
        client = _client(mobile=False, platform="xiaohongshu")
        try:
            # 小红书没有公开热搜 API，尝试从首页推荐获取
            resp = _request_with_retry(client, "GET",
                "https://edith.xiaohongshu.com/api/sns/web/v1/homefeed",
                headers={"Referer": "https://www.xiaohongshu.com/"})
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            results = []
            for i, item in enumerate(items[:30], 1):
                note = item.get("note_card", {})
                results.append({
                    "rank": i,
                    "title": note.get("display_title", ""),
                    "url": f"https://www.xiaohongshu.com/explore/{item.get('id', '')}",
                    "hot_value": _safe_int(note.get("interact_info", {}).get("liked_count", "0")),
                })
            if results:
                return results
            raise RuntimeError("小红书热门数据为空")
        except HANDLED_EXCEPTIONS as e:
            raise RuntimeError(f"小红书热门获取失败（需要登录cookies）: {e}")
        finally:
            _release_client(client)

# ─── B站 ───────────────────────────────────────────────────────────────────────

class BilibiliExtractor(BaseExtractor):
    platform = "bilibili"

    def extract(self, url: str) -> ExtractResult:
        client = _client(mobile=False, platform="bilibili")

        # Handle short links
        if "b23.tv" in url:
            resp = _request_with_retry(client, "GET", url)
            url = str(resp.url)

        bv_m = re.search(r"(BV[\w]+)", url)
        if not bv_m:
            raise ValueError(f"B站: 无法提取 BV 号: {url}")
        bvid = bv_m.group(1)

        # Video info API
        resp = _request_with_retry(client, "GET",
            API_ENDPOINTS["bilibili"]["view"].format(bvid=bvid))
        api_data = resp.json()

        if api_data.get("code") != 0:
            raise ValueError(f"B站 API 错误: {api_data.get('message', 'unknown')}")

        data = api_data["data"]
        aid = data["aid"]

        author = Author(
            nickname=data["owner"]["name"],
            uid=str(data["owner"]["mid"]),
        )
        avatar_url = data["owner"].get("face", "")

        stat = data.get("stat", {})
        stats = Stats(
            views=stat.get("view", 0),
            likes=stat.get("like", 0),
            coins=stat.get("coin", 0),
            collects=stat.get("favorite", 0),
            shares=stat.get("share", 0),
            comments=stat.get("reply", 0),
            danmaku=stat.get("danmaku", 0),
        )

        # Create time
        create_time = _ts_to_iso(data.get("pubdate", 0))

        # Duration
        duration = data.get("duration", 0)

        # Cover
        cover_url = data.get("pic", "")
        if cover_url and not cover_url.startswith("http"):
            cover_url = "https:" + cover_url

        # Tags
        tags = []
        try:
            tag_resp = _request_with_retry(client, "GET",
                f"https://api.bilibili.com/x/tag/archive/tags?bvid={bvid}")
            tag_data = tag_resp.json()
            if tag_data.get("code") == 0:
                tags = [t["tag_name"] for t in tag_data.get("data", [])]
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"B站标签获取失败: {e}")

        # Multi-P detection
        pages_data = data.get("pages", [])
        pages = []
        if len(pages_data) > 1:
            for p in pages_data:
                pages.append({
                    "page": p.get("page", 0),
                    "title": p.get("part", ""),
                    "duration": p.get("duration", 0),
                    "cid": p.get("cid", 0),
                })

        # UP主详情: 粉丝数 + 个人信息
        mid = data["owner"]["mid"]
        try:
            stat_resp = _request_with_retry(client, "GET",
                f"https://api.bilibili.com/x/relation/stat?vmid={mid}")
            stat_data = stat_resp.json()
            if stat_data.get("code") == 0:
                author.followers = stat_data["data"].get("follower", 0)
                author.following = stat_data["data"].get("following", 0)
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"B站UP主粉丝数获取失败: {e}")

        # UP主 bio / total_likes / works_count
        try:
            upstat_resp = _request_with_retry(client, "GET",
                f"https://api.bilibili.com/x/web-interface/card?mid={mid}")
            upstat_data = upstat_resp.json()
            if upstat_data.get("code") == 0:
                card = upstat_data["data"].get("card", {})
                author.bio = card.get("sign", "")
                author.works_count = _safe_int(card.get("article_count", 0)) or _safe_int(upstat_data["data"].get("archive_count", 0))
                author.total_likes = _safe_int(upstat_data["data"].get("like_num", 0))
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"B站UP主详情获取失败: {e}")

        # Play URL + quality list
        cid = data["cid"]
        media = []
        quality_list = []
        try:
            play_resp = _request_with_retry(client, "GET",
                f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=80&fnval=1")
            play_data = play_resp.json()
            if play_data.get("code") == 0:
                durl = play_data["data"].get("durl", [])
                if durl:
                    media.append(MediaItem(url=durl[0]["url"], type="video"))
                # Record available qualities
                qn_map = {120: "4K", 116: "1080P60", 112: "1080P+", 80: "1080P",
                          64: "720P", 32: "480P", 16: "360P"}
                for qn in play_data["data"].get("accept_quality", []):
                    quality_list.append({"qn": qn, "label": qn_map.get(qn, str(qn))})
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"B站视频URL获取失败: {e}")

        if cover_url:
            media.append(MediaItem(url=cover_url, type="image"))

        # Store aid for comments
        self._last_aid = aid

        _release_client(client)
        return ExtractResult(
            platform="bilibili",
            url=url,
            title=data.get("title", ""),
            description=data.get("desc", ""),
            author=author,
            stats=stats,
            media=media,
            tags=tags,
            raw_id=bvid,
            create_time=create_time,
            duration=duration,
            cover_url=cover_url,
            avatar_url=avatar_url,
            pages=pages,
            quality_list=quality_list,
        )

    def fetch_comments(self, bvid: str, cursor: int = 0, count: int = 20, max_pages: int = 1) -> list[Comment]:
        client = _client(mobile=False, platform="bilibili")
        all_comments = []
        max_pages = min(max_pages, 5)
        try:
            # Get aid from bvid
            resp = _request_with_retry(client, "GET",
                API_ENDPOINTS["bilibili"]["view"].format(bvid=bvid))
            aid = resp.json()["data"]["aid"]

            for page in range(max_pages):
                pn = page + 1
                resp = _request_with_retry(client, "GET",
                    f"https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&sort=1&pn={pn}&ps=20")
                data = resp.json()
                replies_list = data.get("data", {}).get("replies", []) or []
                if not replies_list:
                    break
                for r in replies_list:
                    # Fetch sub-replies if count > inline
                    replies = []
                    sub_replies = r.get("replies", []) or []
                    rcount = r.get("rcount", 0)
                    rpid = r.get("rpid", 0)
                    # If there are more sub-replies than inline, fetch them
                    if rcount > len(sub_replies) and rpid:
                        try:
                            sr_resp = _request_with_retry(client, "GET",
                                f"https://api.bilibili.com/x/v2/reply/reply?type=1&oid={aid}&root={rpid}&ps=10&pn=1")
                            sr_data = sr_resp.json()
                            sub_replies = sr_data.get("data", {}).get("replies", []) or sub_replies
                        except HANDLED_EXCEPTIONS:
                            pass
                    for sr in sub_replies[:10]:
                        replies.append(Comment(
                            author=sr.get("member", {}).get("uname", ""),
                            avatar=sr.get("member", {}).get("avatar", ""),
                            content=sr.get("content", {}).get("message", ""),
                            likes=sr.get("like", 0),
                            time=_ts_to_iso(sr.get("ctime", 0)),
                            ip_location=sr.get("reply_control", {}).get("location", ""),
                        ))
                    all_comments.append(Comment(
                        author=r.get("member", {}).get("uname", ""),
                        avatar=r.get("member", {}).get("avatar", ""),
                        content=r.get("content", {}).get("message", ""),
                        likes=r.get("like", 0),
                        time=_ts_to_iso(r.get("ctime", 0)),
                        replies=replies,
                        ip_location=r.get("reply_control", {}).get("location", ""),
                    ))
                if len(all_comments) >= count:
                    break
                time.sleep(0.3)
            return all_comments[:count]
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"B站评论获取失败: {e}")
            return all_comments
        finally:
            _release_client(client)

    def trending(self) -> list[dict]:
        """获取B站热门视频排行榜。"""
        client = _client(mobile=False, platform="bilibili")
        try:
            resp = _request_with_retry(client, "GET",
                API_ENDPOINTS["bilibili"]["popular"])
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"B站热门 API 错误: {data.get('code')}: {data.get('message')}")
            items = data.get("data", {}).get("list", [])
            results = []
            for i, item in enumerate(items, 1):
                results.append({
                    "rank": i,
                    "title": item.get("title", ""),
                    "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                    "hot_value": _safe_int(item.get("stat", {}).get("view", 0)),
                    "author": item.get("owner", {}).get("name", ""),
                    "play": _safe_int(item.get("stat", {}).get("view", 0)),
                    "danmaku": _safe_int(item.get("stat", {}).get("danmaku", 0)),
                })
            return results
        except HANDLED_EXCEPTIONS as e:
            raise RuntimeError(f"B站热门获取失败: {e}")
        finally:
            _release_client(client)

    def extract_user(self, url_or_uid: str) -> dict:
        """获取B站UP主信息。支持 UID 或主页链接。"""
        client = _client(mobile=False, platform="bilibili")
        try:
            # Extract UID from URL or use directly
            uid_match = re.search(r'space\.bilibili\.com/(\d+)', url_or_uid)
            if uid_match:
                mid = uid_match.group(1)
            elif url_or_uid.isdigit():
                mid = url_or_uid
            else:
                raise ValueError(f"无法识别B站UID: {url_or_uid}")

            # User card info
            resp = _request_with_retry(client, "GET",
                f"https://api.bilibili.com/x/web-interface/card?mid={mid}")
            data = resp.json()
            if data.get("code") != 0:
                raise ValueError(f"B站用户API错误: {data.get('message')}")

            card = data["data"].get("card", {})
            archive_count = data["data"].get("archive_count", 0)
            like_num = data["data"].get("like_num", 0)

            # Follower stats
            follower = 0
            following = 0
            try:
                stat_resp = _request_with_retry(client, "GET",
                    f"https://api.bilibili.com/x/relation/stat?vmid={mid}")
                stat_data = stat_resp.json()
                if stat_data.get("code") == 0:
                    follower = stat_data["data"].get("follower", 0)
                    following = stat_data["data"].get("following", 0)
            except HANDLED_EXCEPTIONS:
                pass

            # UP主总播放量
            total_view = 0
            try:
                upstat_resp = _request_with_retry(client, "GET",
                    f"https://api.bilibili.com/x/space/upstat?mid={mid}")
                upstat_data = upstat_resp.json()
                if upstat_data.get("code") == 0:
                    total_view = upstat_data["data"].get("archive", {}).get("view", 0)
            except HANDLED_EXCEPTIONS:
                pass

            # Recent videos
            videos = []
            try:
                vlist_resp = _request_with_retry(client, "GET",
                    f"https://api.bilibili.com/x/space/wbi/arc/search?mid={mid}&ps=10&pn=1&order=pubdate",
                    headers={"Referer": f"https://space.bilibili.com/{mid}"})
                vlist_data = vlist_resp.json()
                if vlist_data.get("code") == 0:
                    for v in vlist_data.get("data", {}).get("list", {}).get("vlist", []):
                        videos.append({
                            "bvid": v.get("bvid", ""),
                            "title": v.get("title", ""),
                            "play": v.get("play", 0),
                            "created": _ts_to_iso(v.get("created", 0)),
                            "url": f"https://www.bilibili.com/video/{v.get('bvid', '')}",
                        })
            except HANDLED_EXCEPTIONS as e:
                logger.warning(f"B站视频列表获取失败: {e}")

            return {
                "platform": "bilibili",
                "uid": mid,
                "nickname": card.get("name", ""),
                "avatar": card.get("face", ""),
                "bio": card.get("sign", ""),
                "level": card.get("level_info", {}).get("current_level", 0),
                "followers": follower,
                "following": following,
                "total_likes": like_num,
                "total_views": total_view,
                "works_count": archive_count,
                "videos": videos,
                "url": f"https://space.bilibili.com/{mid}",
            }
        except HANDLED_EXCEPTIONS as e:
            raise RuntimeError(f"B站用户信息获取失败: {e}")
        finally:
            _release_client(client)

# ─── 微博 ──────────────────────────────────────────────────────────────────────

class WeiboExtractor(BaseExtractor):
    platform = "weibo"

    def _extract_weibo_id(self, url: str) -> str:
        """Extract weibo ID from various URL formats."""
        for pattern in [
            r'/detail/(\d+)', r'/status/(\d+)', r'/(\d{16,})',
            r'weibo\.com/\d+/(\w+)', r'weibo\.cn/\w+/(\w+)',
        ]:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return ""

    def extract(self, url: str) -> ExtractResult:
        client = _client(mobile=False, platform="weibo")

        # First try: resolve short link
        resp = _request_with_retry(client, "GET", url)
        final_url = str(resp.url)

        weibo_id = self._extract_weibo_id(final_url)
        if not weibo_id:
            weibo_id = self._extract_weibo_id(url)
        if not weibo_id:
            raise ValueError(f"微博: 无法提取微博 ID: {final_url}")

        # Strategy 1: PC AJAX API (doesn't need cookie as strictly)
        result = self._try_ajax_api(client, weibo_id, url)
        if result:
            _release_client(client)
            return result

        # Strategy 2: Mobile detail page parsing
        result = self._try_mobile_detail(weibo_id, url)
        if result:
            _release_client(client)
            return result

        _release_client(client)
        raise ValueError(
            "微博: 所有提取方式均失败（微博反爬严格）。\n"
            "  解决方案: 在 ~/.clawkit/cookies.json 中配置微博 cookie:\n"
            '  {"weibo": {"SUB": "你的SUB值", "SUBP": "你的SUBP值"}}\n'
            "  获取方式: 浏览器登录 weibo.com → F12 → Application → Cookies → 复制 SUB/SUBP"
        )

    def _try_ajax_api(self, client: httpx.Client, weibo_id: str, url: str) -> Optional[ExtractResult]:
        """Try weibo.com AJAX API."""
        try:
            api_url = f"https://weibo.com/ajax/statuses/show?id={weibo_id}"
            resp = client.get(api_url, timeout=TIMEOUT)
            if resp.status_code == 403:
                # Try with visitor cookies
                visitor = self._get_visitor_cookies(client)
                if visitor:
                    for k, v in visitor.items():
                        client.cookies.set(k, v)
                    resp = client.get(api_url, timeout=TIMEOUT)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data or ("text_raw" not in data and "text" not in data):
                return None
            return self._parse_weibo_data(data, url, weibo_id)
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"微博 AJAX API 失败: {e}")
            return None

    def _get_visitor_cookies(self, client: httpx.Client) -> dict[str, str]:
        """Generate weibo visitor cookies via their passport API."""
        try:
            # Step 1: generate visitor tid via POST
            import hashlib
            fp = json.dumps({"os":"1","browser":"Chrome125,0,0,0","fonts":"undefined","screenInfo":"2560*1440*30","plugins":""})
            resp = client.post(
                "https://passport.weibo.com/visitor/genvisitor",
                data={"cb": "gen_callback", "fp": fp},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=TIMEOUT,
            )
            m = re.search(r'gen_callback\((.*?)\)', resp.text)
            if not m:
                # Try GET fallback
                resp = client.get(
                    "https://passport.weibo.com/visitor/genvisitor",
                    params={"cb": "gen_callback", "fp": fp},
                    timeout=TIMEOUT,
                )
                m = re.search(r'gen_callback\((.*?)\)', resp.text)
            if not m:
                return {}
            data = json.loads(m.group(1))
            tid = data.get("data", {}).get("tid", "")
            if not tid:
                return {}

            # Step 2: incarnate to get SUB cookie
            resp = client.get(
                "https://passport.weibo.com/visitor/visitor",
                params={"a": "incarnate", "t": tid, "w": 2, "cb": "cross_domain", "from": "weibo"},
                timeout=TIMEOUT,
            )
            m = re.search(r'cross_domain\((.*?)\)', resp.text)
            if not m:
                return {}
            data = json.loads(m.group(1))
            sub = data.get("data", {}).get("sub", "")
            subp = data.get("data", {}).get("subp", "")
            if sub:
                return {"SUB": sub, "SUBP": subp}
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"微博 visitor cookie 获取失败: {e}")
        return {}

    def _try_mobile_detail(self, weibo_id: str, url: str) -> Optional[ExtractResult]:
        """Try m.weibo.cn detail page and API."""
        try:
            client = _client(mobile=True, platform="weibo")
            client.headers["Referer"] = "https://m.weibo.cn/"
            client.headers["X-Requested-With"] = "XMLHttpRequest"

            # Strategy 1: Mobile statuses/show JSON API
            try:
                resp = client.get(f"https://m.weibo.cn/statuses/show?id={weibo_id}", timeout=TIMEOUT)
                if resp.status_code == 200:
                    result = resp.json()
                    data = result.get("data", {})
                    if data and data.get("text"):
                        _release_client(client)
                        return self._parse_weibo_data(data, url, weibo_id)
            except HANDLED_EXCEPTIONS:
                pass

            # Strategy 2: Detail page with render_data
            try:
                resp = client.get(f"https://m.weibo.cn/detail/{weibo_id}", timeout=TIMEOUT)
                page = resp.text

                # Handle visitor system redirect - if we get it, the page needs JS
                if "Sina Visitor System" in page:
                    logger.debug("微博: 遇到 Visitor System，尝试获取 visitor cookie")
                    # Get visitor cookies using desktop client
                    desktop_client = _client(mobile=False, platform="weibo")
                    visitor = self._get_visitor_cookies(desktop_client)
                    desktop__release_client(client)
                    if visitor:
                        for k, v in visitor.items():
                            client.cookies.set(k, v)
                        resp = client.get(f"https://m.weibo.cn/detail/{weibo_id}", timeout=TIMEOUT)
                        page = resp.text

                m = re.search(r'var \$render_data\s*=\s*(\[.*?\])\[0\]', page, re.DOTALL)
                if m:
                    render_data = json.loads(m.group(1))
                    if render_data and isinstance(render_data, list) and render_data[0]:
                        data = render_data[0].get("status", {})
                        if data:
                            _release_client(client)
                            return self._parse_weibo_data(data, url, weibo_id)
            except HANDLED_EXCEPTIONS as e:
                logger.debug(f"微博 detail 页面解析失败: {e}")

            _release_client(client)
            return None
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"微博移动端解析失败: {e}")
            return None

    def _parse_weibo_data(self, data: dict, url: str, weibo_id: str) -> ExtractResult:
        """Parse weibo data from either API."""
        text_raw = data.get("text_raw", "") or data.get("text", "")
        # Clean HTML
        text_clean = re.sub(r'<[^>]+>', '', text_raw)
        text_clean = html.unescape(text_clean).strip()

        user = data.get("user", {})
        author = Author(
            nickname=user.get("screen_name", "") or user.get("name", ""),
            uid=str(user.get("id", "") or user.get("idstr", "")),
        )
        avatar_url = user.get("avatar_hd", "") or user.get("profile_image_url", "")

        stats = Stats(
            reposts=_safe_int(data.get("reposts_count", 0)),
            comments=_safe_int(data.get("comments_count", 0)),
            likes=_safe_int(data.get("attitudes_count", 0)),
        )

        # Create time
        create_time = data.get("created_at", "")
        # Try to parse weibo date format: "Wed Jan 01 00:00:00 +0800 2025"
        if create_time and not create_time[0].isdigit():
            try:
                dt = datetime.strptime(create_time, "%a %b %d %H:%M:%S %z %Y")
                create_time = dt.isoformat()
            except ValueError:
                pass

        media = []
        # Images
        pics = data.get("pics", []) or data.get("pic_infos", {})
        if isinstance(pics, list):
            for pic in pics:
                large = pic.get("large", {})
                img_url = large.get("url", pic.get("url", ""))
                if img_url:
                    media.append(MediaItem(url=img_url, type="image"))
        elif isinstance(pics, dict):
            for pid, pic in pics.items():
                large = pic.get("largest", {}) or pic.get("large", {})
                img_url = large.get("url", "")
                if img_url:
                    media.append(MediaItem(url=img_url, type="image"))

        # Video
        page_info = data.get("page_info", {})
        if page_info.get("type") == "video" or page_info.get("object_type") == "video":
            urls_obj = page_info.get("urls", {}) or page_info.get("media_info", {})
            v_url = (urls_obj.get("mp4_720p_mp4", "") or urls_obj.get("mp4_hd_url", "")
                     or urls_obj.get("mp4_sd_url", "") or urls_obj.get("stream_url", ""))
            if v_url:
                media.append(MediaItem(url=v_url, type="video"))

        # Also check mix_media_info for newer weibo format
        mix_media = data.get("mix_media_info", {}).get("items", [])
        for mm in mix_media:
            if mm.get("type") == "pic":
                img_url = mm.get("data", {}).get("largest", {}).get("url", "")
                if img_url:
                    media.append(MediaItem(url=img_url, type="image"))
            elif mm.get("type") == "video":
                v_data = mm.get("data", {})
                v_url = (v_data.get("media_info", {}).get("mp4_720p_mp4", "")
                         or v_data.get("media_info", {}).get("mp4_hd_url", ""))
                if v_url:
                    media.append(MediaItem(url=v_url, type="video"))

        tags = re.findall(r"#([^#]+)#", text_raw)

        # Location
        location = ""
        region = data.get("region_name", "")
        if region:
            location = region.replace("发布于 ", "")

        return ExtractResult(
            platform="weibo",
            url=url,
            title=text_clean[:100],
            description=text_clean,
            author=author,
            stats=stats,
            media=media,
            tags=tags,
            raw_id=weibo_id,
            create_time=create_time,
            avatar_url=avatar_url,
            location=location,
        )

    def trending(self) -> list[dict]:
        """获取微博热搜榜。"""
        client = _client(mobile=False, platform="weibo")
        try:
            resp = _request_with_retry(client, "GET",
                "https://weibo.com/ajax/side/hotSearch",
                headers={"Referer": "https://weibo.com/", "X-Requested-With": "XMLHttpRequest"})
            data = resp.json()
            realtime = data.get("data", {}).get("realtime", [])
            results = []
            for i, item in enumerate(realtime, 1):
                word = item.get("word", "")
                results.append({
                    "rank": i,
                    "title": item.get("note", word),
                    "url": f"https://s.weibo.com/weibo?q=%23{word}%23",
                    "hot_value": _safe_int(item.get("num", 0)),
                    "category": item.get("category", ""),
                    "is_hot": bool(item.get("is_hot")),
                    "is_new": bool(item.get("is_new")),
                })
            return results
        except HANDLED_EXCEPTIONS as e:
            raise RuntimeError(f"微博热搜获取失败: {e}")
        finally:
            _release_client(client)

# ─── 知乎 ──────────────────────────────────────────────────────────────────────

class ZhihuExtractor(BaseExtractor):
    platform = "zhihu"

    def extract(self, url: str) -> ExtractResult:
        # Zhihu blocks without proper headers; use a zhihu-specific client
        client = httpx.Client(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers={
                "User-Agent": DESKTOP_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.zhihu.com/",
                "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "same-origin",
            },
            cookies=_get_cookies("zhihu"),
        )

        try:
            resp = client.get(url)
        except httpx.HTTPStatusError:
            # Try with mobile UA
            client.headers["User-Agent"] = MOBILE_UA
            resp = client.get(url)
        final_url = str(resp.url)
        page = resp.text

        # Zhuanlan article
        m_article = re.search(r'zhuanlan\.zhihu\.com/p/(\d+)', final_url)
        if m_article:
            result = self._extract_from_page(page, final_url, url, "article", m_article.group(1))
            _release_client(client)
            return result

        # Answer
        m_answer = re.search(r'question/(\d+)/answer/(\d+)', final_url)
        if m_answer:
            result = self._extract_from_page(page, final_url, url, "answer", m_answer.group(2))
            _release_client(client)
            return result

        # Question
        m_question = re.search(r'question/(\d+)', final_url)
        if m_question:
            result = self._extract_from_page(page, final_url, url, "question", m_question.group(1))
            _release_client(client)
            return result

        _release_client(client)
        raise ValueError(f"知乎: 无法解析 URL: {final_url}")

    def _extract_from_page(self, page: str, final_url: str, orig_url: str,
                           content_type: str, content_id: str) -> ExtractResult:
        """Extract data from page HTML using js-initialData."""
        # Check for anti-bot challenge page
        if 'zse-ck' in page and len(page) < 2000:
            logger.warning("知乎: 遇到反爬验证页面")
            return self._try_api(content_type, content_id, orig_url)

        # Try to find initialData JSON
        m = re.search(r'<script\s+id="js-initialData"[^>]*>(.*?)</script>', page, re.DOTALL)
        if m:
            try:
                initial_data = json.loads(m.group(1))
                return self._parse_initial_data(initial_data, content_type, content_id, orig_url)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"知乎 initialData 解析失败: {e}")

        # Fallback: try API (may fail without cookie)
        return self._try_api(content_type, content_id, orig_url)

    def _parse_initial_data(self, data: dict, content_type: str,
                            content_id: str, url: str) -> ExtractResult:
        """Parse zhihu initialData JSON."""
        init = data.get("initialState", {})

        if content_type == "article":
            articles = init.get("entities", {}).get("articles", {})
            article = articles.get(content_id, {})
            if not article:
                raise ValueError("知乎: 文章数据未找到")
            content = re.sub(r'<[^>]+>', '', article.get("content", ""))
            author_data = article.get("author", {})
            create_time = _ts_to_iso(article.get("created", 0))
            return ExtractResult(
                platform="zhihu", url=url,
                title=article.get("title", ""),
                description=content[:500],
                author=Author(
                    nickname=author_data.get("name", ""),
                    uid=author_data.get("urlToken", ""),
                ),
                avatar_url=author_data.get("avatarUrl", ""),
                stats=Stats(
                    likes=article.get("voteupCount", 0),
                    comments=article.get("commentCount", 0),
                ),
                raw_id=content_id,
                create_time=create_time,
            )

        elif content_type == "answer":
            answers = init.get("entities", {}).get("answers", {})
            answer = answers.get(content_id, {})
            if not answer:
                raise ValueError("知乎: 回答数据未找到")
            content = re.sub(r'<[^>]+>', '', answer.get("content", ""))
            author_data = answer.get("author", {})
            question = answer.get("question", {})
            create_time = _ts_to_iso(answer.get("createdTime", 0))
            return ExtractResult(
                platform="zhihu", url=url,
                title=question.get("title", ""),
                description=content[:500],
                author=Author(
                    nickname=author_data.get("name", ""),
                    uid=author_data.get("urlToken", ""),
                ),
                avatar_url=author_data.get("avatarUrl", ""),
                stats=Stats(
                    likes=answer.get("voteupCount", 0),
                    comments=answer.get("commentCount", 0),
                ),
                raw_id=content_id,
                create_time=create_time,
            )

        else:  # question
            questions = init.get("entities", {}).get("questions", {})
            question = questions.get(content_id, {})
            if not question:
                raise ValueError("知乎: 问题数据未找到")
            detail = re.sub(r'<[^>]+>', '', question.get("detail", ""))
            return ExtractResult(
                platform="zhihu", url=url,
                title=question.get("title", ""),
                description=detail[:500],
                stats=Stats(
                    views=question.get("visitCount", 0),
                    comments=question.get("answerCount", 0),
                ),
                tags=[t.get("name", "") for t in question.get("topics", [])],
                raw_id=content_id,
            )

    def _try_api(self, content_type: str, content_id: str, url: str) -> ExtractResult:
        """Fallback: try zhihu API directly."""
        client = _client(mobile=False, platform="zhihu")
        try:
            if content_type == "article":
                api = f"https://www.zhihu.com/api/v4/articles/{content_id}"
            elif content_type == "answer":
                # Need question id - try to extract from URL
                m = re.search(r'question/(\d+)', url)
                qid = m.group(1) if m else ""
                api = f"https://www.zhihu.com/api/v4/questions/{qid}/answers/{content_id}?include=content,voteup_count,comment_count"
            else:
                api = f"https://www.zhihu.com/api/v4/questions/{content_id}?include=detail,answer_count,follower_count,visit_count"

            resp = _request_with_retry(client, "GET", api)
            data = resp.json()

            if "error" in data:
                raise ValueError(f"知乎 API 错误: {data['error'].get('message', '')}")

            if content_type == "article":
                content = re.sub(r'<[^>]+>', '', data.get("content", ""))
                author_data = data.get("author", {})
                return ExtractResult(
                    platform="zhihu", url=url,
                    title=data.get("title", ""),
                    description=content[:500],
                    author=Author(nickname=author_data.get("name", ""),
                                  uid=author_data.get("url_token", "")),
                    stats=Stats(likes=data.get("voteup_count", 0),
                                comments=data.get("comment_count", 0)),
                    raw_id=content_id,
                )
            elif content_type == "answer":
                content = re.sub(r'<[^>]+>', '', data.get("content", ""))
                author_data = data.get("author", {})
                question = data.get("question", {})
                return ExtractResult(
                    platform="zhihu", url=url,
                    title=question.get("title", ""),
                    description=content[:500],
                    author=Author(nickname=author_data.get("name", ""),
                                  uid=author_data.get("url_token", "")),
                    stats=Stats(likes=data.get("voteup_count", 0),
                                comments=data.get("comment_count", 0)),
                    raw_id=content_id,
                )
            else:
                return ExtractResult(
                    platform="zhihu", url=url,
                    title=data.get("title", ""),
                    description=re.sub(r'<[^>]+>', '', data.get("detail", "")),
                    stats=Stats(views=data.get("visit_count", 0),
                                comments=data.get("answer_count", 0)),
                    tags=[t.get("name", "") for t in data.get("topics", [])],
                    raw_id=content_id,
                )
        except HANDLED_EXCEPTIONS as e:
            raise ValueError(
                f"知乎: 提取失败 ({e})。知乎反爬严格，需要配置 cookie。\n"
                "  解决方案: 在 ~/.clawkit/cookies.json 中配置:\n"
                '  {"zhihu": {"z_c0": "你的z_c0值"}}\n'
                "  获取方式: 浏览器登录 zhihu.com → F12 → Application → Cookies → 复制 z_c0"
            )
        finally:
            _release_client(client)

    def trending(self) -> list[dict]:
        """获取知乎热榜。"""
        client = _client(mobile=True, platform="zhihu")
        try:
            # Use mobile API (no auth required)
            resp = _request_with_retry(client, "GET",
                "https://api.zhihu.com/topstory/hot-lists/total?limit=50")
            data = resp.json()
            items = data.get("data", [])
            results = []
            for i, item in enumerate(items, 1):
                target = item.get("target", {})
                title = target.get("title", "")
                qid = target.get("id", "")
                url = f"https://www.zhihu.com/question/{qid}" if qid else ""
                detail_text = item.get("detail_text", "")
                # Parse hot value from detail_text like "2345 万热度"
                hot_match = re.search(r'([\d.]+)\s*万', detail_text)
                hot_value = int(float(hot_match.group(1)) * 10000) if hot_match else 0
                results.append({
                    "rank": i,
                    "title": title,
                    "url": url,
                    "hot_value": hot_value,
                    "excerpt": target.get("excerpt", "")[:100],
                })
            return results
        except HANDLED_EXCEPTIONS as e:
            raise RuntimeError(f"知乎热榜获取失败: {e}")
        finally:
            _release_client(client)

# ─── 快手 ──────────────────────────────────────────────────────────────────────

class KuaishouExtractor(BaseExtractor):
    platform = "kuaishou"

    def extract(self, url: str) -> ExtractResult:
        # Try mobile endpoint first (less anti-crawl)
        result = self._try_mobile(url)
        if result and (result.title or result.author.nickname):
            return result

        # Try PC endpoint
        result = self._try_pc(url)
        if result and (result.title or result.author.nickname):
            return result

        if result and not result.title and not result.author.nickname:
            raise ValueError(
                "快手: 反爬严格，无法提取数据。\n"
                "  解决方案: 在 ~/.clawkit/cookies.json 中配置:\n"
                '  {"kuaishou": {"did": "你的did值", "didv": "你的didv值"}}\n'
                "  获取方式: 浏览器打开 kuaishou.com → F12 → Application → Cookies"
            )
        return result or ExtractResult(platform="kuaishou", url=url)

    def _try_mobile(self, url: str) -> Optional[ExtractResult]:
        """Try m.kuaishou.com."""
        try:
            client = _client(mobile=True, platform="kuaishou")
            resp = _request_with_retry(client, "GET", url)
            final_url = str(resp.url)
            page = resp.text

            video_id = ""
            m = re.search(r'/short-video/(\w+)', final_url) or re.search(r'/fw/photo/(\w+)', final_url)
            if m:
                video_id = m.group(1)

            return self._parse_page(page, url, video_id)
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"快手移动端失败: {e}")
            return None

    def _try_pc(self, url: str) -> Optional[ExtractResult]:
        """Try www.kuaishou.com."""
        try:
            client = _client(mobile=False, platform="kuaishou")
            resp = _request_with_retry(client, "GET", url)
            final_url = str(resp.url)
            page = resp.text

            video_id = ""
            m = re.search(r'/short-video/(\w+)', final_url) or re.search(r'/fw/photo/(\w+)', final_url)
            if m:
                video_id = m.group(1)

            return self._parse_page(page, url, video_id)
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"快手PC端失败: {e}")
            return None

    def _parse_page(self, page: str, url: str, video_id: str) -> ExtractResult:
        """Parse kuaishou page content."""
        title = ""
        description = ""
        author = Author()
        stats = Stats()
        media = []
        tags = []
        create_time = ""
        cover_url = ""
        avatar_url = ""

        # Try __APOLLO_STATE__
        m = re.search(r'window\.__APOLLO_STATE__\s*=\s*(.*?);?\s*</script>', page, re.DOTALL)
        if m:
            state = None
            raw = m.group(1).strip()
            try:
                state = json.loads(raw)
            except json.JSONDecodeError:
                # Kuaishou may truncate/corrupt JSON; try to salvage by trimming
                for trim in range(1, min(200, len(raw))):
                    try:
                        state = json.loads(raw[:-trim] + "}")
                        break
                    except json.JSONDecodeError:
                        try:
                            state = json.loads(raw[:-trim] + "}}")
                            break
                        except json.JSONDecodeError:
                            continue
                if not state:
                    logger.warning("快手 APOLLO_STATE JSON 损坏，使用正则回退")
            if state:
                # Iterate all keys - don't break early, collect both photo and author
                for key, val in state.items():
                    if not isinstance(val, dict):
                        continue
                    if "VisionVideoDetailPhoto" in key and not title:
                        title = val.get("caption", "") or val.get("title", "")
                        description = title
                        create_time = _ts_to_iso(val.get("timestamp", 0))
                        stats = Stats(
                            likes=_safe_int(val.get("likeCount", 0)),
                            comments=_safe_int(val.get("commentCount", 0)),
                            views=_safe_int(val.get("viewCount", 0)),
                            shares=_safe_int(val.get("shareCount", 0)),
                        )
                        v_url = val.get("photoUrl", "")
                        if v_url:
                            media.append(MediaItem(url=v_url, type="video"))
                        cover_ref = val.get("coverUrl", "")
                        if cover_ref:
                            cover_url = cover_ref
                    elif "VisionVideoDetailAuthor" in key and not author.nickname:
                        author = Author(
                            nickname=val.get("name", ""),
                            uid=val.get("id", ""),
                        )
                        avatar_url = val.get("headerUrl", "")

            # Regex fallback for fields not found in JSON
            if not title:
                cap = re.search(r'"caption"\s*:\s*"([^"]*)"', raw)
                if cap:
                    title = cap.group(1)
                    description = title
            if not author.nickname:
                nm = re.search(r'"name"\s*:\s*"([^"]*)"', raw)
                if nm:
                    author.nickname = nm.group(1)

        # Try __NUXT__
        if not title:
            m = re.search(r'window\.__NUXT__\s*=\s*(.*?);?\s*</script>', page, re.DOTALL)
            if m:
                try:
                    raw = m.group(1).strip().replace("undefined", "null")
                    state = json.loads(raw)
                    video_info = state.get("data", [{}])[0] if isinstance(state.get("data"), list) else state.get("data", {})
                    if isinstance(video_info, dict):
                        title = video_info.get("caption", "") or video_info.get("title", "")
                        description = title
                except (json.JSONDecodeError, IndexError) as e:
                    logger.warning(f"快手 NUXT 解析失败: {e}")

        # Fallback: meta tags (always try to fill missing fields)
        if not title:
            m_title = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"', page)
            if not m_title:
                m_title = re.search(r'<meta[^>]*name="title"[^>]*content="([^"]*)"', page)
            if m_title:
                title = html.unescape(m_title.group(1))
        if not description:
            m_desc = re.search(r'<meta[^>]*(?:property="og:description"|name="description")[^>]*content="([^"]*)"', page)
            if m_desc:
                description = html.unescape(m_desc.group(1))
        if not media:
            m_video = re.search(r'<meta[^>]*property="og:video(?::url)?"[^>]*content="([^"]*)"', page)
            if m_video:
                media.append(MediaItem(url=html.unescape(m_video.group(1)), type="video"))
        if not cover_url:
            m_image = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]*)"', page)
            if m_image:
                cover_url = html.unescape(m_image.group(1))
        if not author.nickname:
            # Try <title> tag: "xxx的作品 - 快手"
            m_author = re.search(r'<title[^>]*>([^<]*?)的作品', page)
            if m_author:
                author.nickname = html.unescape(m_author.group(1).strip())

        return ExtractResult(
            platform="kuaishou",
            url=url,
            title=title,
            description=description or title,
            author=author,
            stats=stats,
            media=media,
            tags=tags,
            raw_id=video_id,
            create_time=create_time,
            cover_url=cover_url,
            avatar_url=avatar_url,
        )

# ─── YouTube ───────────────────────────────────────────────────────────────────

class YoutubeExtractor(BaseExtractor):
    platform = "youtube"

    def extract(self, url: str) -> ExtractResult:
        try:
            proc = subprocess.run(
                ["yt-dlp", "--dump-json", "--no-download", url],
                capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError:
            raise ValueError("YouTube: 需要安装 yt-dlp (brew install yt-dlp)")

        if proc.returncode != 0:
            raise ValueError(f"YouTube: yt-dlp 错误: {proc.stderr.strip()[:200]}")

        data = json.loads(proc.stdout)

        media = []
        v_url = data.get("url", "")
        if v_url:
            media.append(MediaItem(url=v_url, type="video",
                                   width=data.get("width", 0),
                                   height=data.get("height", 0)))
        thumb = data.get("thumbnail", "")
        if thumb:
            media.append(MediaItem(url=thumb, type="image"))

        create_time = ""
        upload_date = data.get("upload_date", "")
        if upload_date and len(upload_date) == 8:
            try:
                create_time = datetime.strptime(upload_date, "%Y%m%d").isoformat()
            except ValueError:
                pass

        return ExtractResult(
            platform="youtube",
            url=url,
            title=data.get("title", ""),
            description=(data.get("description", "") or "")[:500],
            author=Author(
                nickname=data.get("channel", "") or data.get("uploader", ""),
                uid=data.get("channel_id", ""),
            ),
            stats=Stats(
                views=data.get("view_count", 0) or 0,
                likes=data.get("like_count", 0) or 0,
                comments=data.get("comment_count", 0) or 0,
            ),
            media=media,
            tags=(data.get("tags", []) or [])[:20],
            raw_id=data.get("id", ""),
            create_time=create_time,
            duration=data.get("duration", 0) or 0,
            cover_url=thumb,
            avatar_url=data.get("uploader_url", ""),
        )

# ─── Twitter/X ─────────────────────────────────────────────────────────────────

class TwitterExtractor(BaseExtractor):
    platform = "twitter"

    # Twitter bearer token (public, used by web client)
    _BEARER = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

    def _extract_tweet_id(self, url: str) -> str:
        """Extract tweet ID from URL."""
        m = re.search(r'/status/(\d+)', url)
        if m:
            return m.group(1)
        # Resolve short URL
        client = _client(mobile=False)
        resp = client.get(url)
        final = str(resp.url)
        _release_client(client)
        m = re.search(r'/status/(\d+)', final)
        if m:
            return m.group(1)
        raise ValueError(f"Twitter: 无法提取推文 ID: {url}")

    def _extract_screen_name(self, url: str) -> str:
        """Extract screen_name from URL."""
        m = re.search(r'(?:twitter\.com|x\.com)/(\w+)/status/', url)
        return m.group(1) if m else ""

    def _try_fxtwitter(self, tweet_id: str, screen_name: str) -> Optional[ExtractResult]:
        """Primary: FxTwitter API - rich structured JSON, no auth needed."""
        try:
            url_path = f"{screen_name}/status/{tweet_id}" if screen_name else f"i/status/{tweet_id}"
            api_url = API_ENDPOINTS["twitter"]["fxtwitter_status"].format(url_path=url_path)
            client = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "clawkit/3.0"})
            resp = client.get(api_url)
            _release_client(client)
            if resp.status_code != 200:
                return None
            data = resp.json()
            tweet = data.get("tweet", {})
            if not tweet:
                return None

            author_data = tweet.get("author", {})
            author = Author(
                nickname=author_data.get("name", ""),
                uid=author_data.get("id", ""),
                sec_uid=author_data.get("screen_name", ""),
                bio=author_data.get("description", ""),
                followers=_safe_int(author_data.get("followers", 0)),
                following=_safe_int(author_data.get("following", 0)),
                total_likes=_safe_int(author_data.get("likes", 0)),
                works_count=_safe_int(author_data.get("tweets", 0)),
            )
            avatar_url = author_data.get("avatar_url", "")

            stats = Stats(
                likes=_safe_int(tweet.get("likes", 0)),
                reposts=_safe_int(tweet.get("retweets", 0)),
                comments=_safe_int(tweet.get("replies", 0)),
                shares=_safe_int(tweet.get("quotes", 0)),
                views=_safe_int(tweet.get("views", 0)),
                collects=_safe_int(tweet.get("bookmarks", 0)),
            )

            media = []
            # Video
            video_data = tweet.get("media", {}).get("videos", [])
            for v in video_data:
                v_url = v.get("url", "")
                if v_url:
                    media.append(MediaItem(
                        url=v_url, type="video",
                        width=v.get("width", 0), height=v.get("height", 0),
                    ))
            # Images
            photos = tweet.get("media", {}).get("photos", [])
            for p in photos:
                media.append(MediaItem(
                    url=p.get("url", ""),
                    type="image",
                    width=p.get("width", 0), height=p.get("height", 0),
                ))

            # Tags from text
            text = tweet.get("text", "")
            tags = re.findall(r"#(\w+)", text)

            # Duration (video)
            duration = 0
            if video_data:
                duration = int(video_data[0].get("duration", 0))

            # Cover
            cover_url = tweet.get("media", {}).get("videos", [{}])[0].get("thumbnail_url", "") if video_data else ""
            if not cover_url and photos:
                cover_url = photos[0].get("url", "")

            create_time = tweet.get("created_at", "")

            return ExtractResult(
                platform="twitter",
                url=tweet.get("url", f"https://x.com/{screen_name}/status/{tweet_id}"),
                title=text[:100] if text else "",
                description=text,
                author=author,
                stats=stats,
                media=media,
                tags=tags,
                raw_id=tweet_id,
                create_time=create_time,
                duration=duration,
                cover_url=cover_url,
                avatar_url=avatar_url,
            )
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"FxTwitter API 失败: {e}")
            return None

    def _try_syndication(self, tweet_id: str) -> Optional[ExtractResult]:
        """Fallback: Twitter syndication API - no auth, limited stats."""
        try:
            api_url = API_ENDPOINTS["twitter"]["syndication"].format(tweet_id=tweet_id)
            client = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": DESKTOP_UA})
            resp = client.get(api_url)
            _release_client(client)
            if resp.status_code != 200:
                return None
            data = resp.json()

            user = data.get("user", {})
            author = Author(
                nickname=user.get("name", ""),
                uid=user.get("id_str", ""),
                sec_uid=user.get("screen_name", ""),
            )
            avatar_url = user.get("profile_image_url_https", "").replace("_normal", "")

            stats = Stats(
                likes=_safe_int(data.get("favorite_count", 0)),
                comments=_safe_int(data.get("conversation_count", 0)),
            )

            media = []
            # Video
            video = data.get("video", {})
            if video:
                variants = video.get("variants", [])
                # Pick highest bitrate mp4
                mp4s = [v for v in variants if v.get("type") == "video/mp4"]
                if mp4s:
                    best = max(mp4s, key=lambda x: x.get("src", "").count("1080") or 0)
                    media.append(MediaItem(url=best.get("src", ""), type="video"))
                cover_url = video.get("poster", "")
            else:
                cover_url = ""

            # Photos
            for p in data.get("photos", []):
                media.append(MediaItem(url=p.get("url", ""), type="image"))

            # MediaDetails (alternative)
            if not media:
                for md in data.get("mediaDetails", []):
                    if md.get("type") == "video":
                        vi = md.get("video_info", {})
                        variants = vi.get("variants", [])
                        mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
                        if mp4s:
                            best = max(mp4s, key=lambda x: x.get("bitrate", 0))
                            media.append(MediaItem(url=best.get("url", ""), type="video"))
                    elif md.get("type") == "photo":
                        media.append(MediaItem(url=md.get("media_url_https", ""), type="image"))

            text = data.get("text", "")
            tags = re.findall(r"#(\w+)", text)
            create_time = data.get("created_at", "")
            duration = int(video.get("durationMs", 0)) // 1000 if video else 0

            return ExtractResult(
                platform="twitter",
                url=f"https://x.com/{user.get('screen_name', 'i')}/status/{tweet_id}",
                title=text[:100] if text else "",
                description=text,
                author=author,
                stats=stats,
                media=media,
                tags=tags,
                raw_id=tweet_id,
                create_time=create_time,
                duration=duration,
                cover_url=cover_url,
                avatar_url=avatar_url,
            )
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"Syndication API 失败: {e}")
            return None

    def _try_guest_graphql(self, tweet_id: str) -> Optional[ExtractResult]:
        """Fallback: Guest token + GraphQL API - full data but may be rate limited."""
        try:
            client = httpx.Client(timeout=TIMEOUT, headers={
                "User-Agent": DESKTOP_UA,
                "Authorization": f"Bearer {self._BEARER}",
            })
            # Get guest token
            resp = client.post("https://api.twitter.com/1.1/guest/activate.json")
            if resp.status_code != 200:
                _release_client(client)
                return None
            guest_token = resp.json().get("guest_token", "")
            if not guest_token:
                _release_client(client)
                return None

            client.headers["x-guest-token"] = guest_token

            # GraphQL query
            variables = json.dumps({"tweetId": tweet_id, "withCommunity": False, "includePromotedContent": False, "withVoice": False})
            features = json.dumps({
                "creator_subscriptions_tweet_preview_api_enabled": True,
                "tweetypie_unmention_optimization_enabled": True,
                "responsive_web_edit_tweet_api_enabled": True,
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
                "view_counts_everywhere_api_enabled": True,
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": False,
                "tweet_awards_web_tipping_enabled": False,
                "freedom_of_speech_not_reach_fetch_enabled": True,
                "standardized_nudges_misinfo": True,
                "longform_notetweets_rich_text_read_enabled": True,
                "longform_notetweets_inline_media_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "responsive_web_media_download_video_enabled": False,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_enhance_cards_enabled": False,
            })
            from urllib.parse import quote
            api_url = f"https://twitter.com/i/api/graphql/0hWvDhmW8YQ-S_ib3azIrw/TweetResultByRestId?variables={quote(variables)}&features={quote(features)}"
            resp = client.get(api_url)
            _release_client(client)

            if resp.status_code != 200:
                return None
            result = resp.json()
            tweet_result = result.get("data", {}).get("tweetResult", {}).get("result", {})
            if not tweet_result or tweet_result.get("__typename") == "TweetUnavailable":
                return None

            legacy = tweet_result.get("legacy", {})
            core = tweet_result.get("core", {}).get("user_results", {}).get("result", {})
            user_legacy = core.get("legacy", {})

            author = Author(
                nickname=user_legacy.get("name", ""),
                uid=user_legacy.get("id_str", core.get("rest_id", "")),
                sec_uid=user_legacy.get("screen_name", ""),
                bio=user_legacy.get("description", ""),
                followers=_safe_int(user_legacy.get("followers_count", 0)),
                following=_safe_int(user_legacy.get("friends_count", 0)),
                total_likes=_safe_int(user_legacy.get("favourites_count", 0)),
                works_count=_safe_int(user_legacy.get("statuses_count", 0)),
            )
            avatar_url = user_legacy.get("profile_image_url_https", "").replace("_normal", "")

            views_data = tweet_result.get("views", {})
            stats = Stats(
                likes=_safe_int(legacy.get("favorite_count", 0)),
                reposts=_safe_int(legacy.get("retweet_count", 0)),
                comments=_safe_int(legacy.get("reply_count", 0)),
                shares=_safe_int(legacy.get("quote_count", 0)),
                views=_safe_int(views_data.get("count", 0)),
                collects=_safe_int(legacy.get("bookmark_count", 0)),
            )

            media = []
            ext_media = legacy.get("extended_entities", {}).get("media", [])
            duration = 0
            cover_url = ""
            for m in ext_media:
                if m.get("type") == "video" or m.get("type") == "animated_gif":
                    vi = m.get("video_info", {})
                    variants = vi.get("variants", [])
                    mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
                    if mp4s:
                        best = max(mp4s, key=lambda x: x.get("bitrate", 0))
                        media.append(MediaItem(url=best.get("url", ""), type="video",
                                               width=m.get("original_info", {}).get("width", 0),
                                               height=m.get("original_info", {}).get("height", 0)))
                    duration = vi.get("duration_millis", 0) // 1000
                    cover_url = m.get("media_url_https", "")
                elif m.get("type") == "photo":
                    media.append(MediaItem(url=m.get("media_url_https", ""), type="image",
                                           width=m.get("original_info", {}).get("width", 0),
                                           height=m.get("original_info", {}).get("height", 0)))

            text = legacy.get("full_text", "")
            tags = [h.get("text", "") for h in legacy.get("entities", {}).get("hashtags", [])]
            create_time = legacy.get("created_at", "")

            return ExtractResult(
                platform="twitter",
                url=f"https://x.com/{user_legacy.get('screen_name', 'i')}/status/{tweet_id}",
                title=text[:100] if text else "",
                description=text,
                author=author,
                stats=stats,
                media=media,
                tags=tags,
                raw_id=tweet_id,
                create_time=create_time,
                duration=duration,
                cover_url=cover_url,
                avatar_url=avatar_url,
            )
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"Guest GraphQL 失败: {e}")
            return None

    def _try_ytdlp(self, url: str) -> Optional[ExtractResult]:
        """Last resort: yt-dlp for video tweets."""
        try:
            proc = subprocess.run(
                ["yt-dlp", "--dump-json", "--no-download", url],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                media = []
                v_url = data.get("url", "")
                if v_url:
                    media.append(MediaItem(url=v_url, type="video"))
                thumb = data.get("thumbnail", "")
                if thumb:
                    media.append(MediaItem(url=thumb, type="image"))
                create_time = _ts_to_iso(data.get("timestamp")) if data.get("timestamp") else ""
                return ExtractResult(
                    platform="twitter", url=url,
                    title=data.get("title", "") or (data.get("description", "") or "")[:100],
                    description=data.get("description", ""),
                    author=Author(nickname=data.get("uploader", ""), uid=data.get("uploader_id", "")),
                    stats=Stats(likes=data.get("like_count", 0) or 0, reposts=data.get("repost_count", 0) or 0, comments=data.get("comment_count", 0) or 0),
                    media=media, raw_id=data.get("id", ""), create_time=create_time,
                    duration=data.get("duration", 0) or 0,
                )
        except FileNotFoundError:
            logger.debug("yt-dlp 未安装")
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"yt-dlp Twitter 提取失败: {e}")
        return None

    def extract(self, url: str) -> ExtractResult:
        tweet_id = self._extract_tweet_id(url)
        screen_name = self._extract_screen_name(url)

        # Strategy 1: FxTwitter API (most reliable, rich data)
        result = self._try_fxtwitter(tweet_id, screen_name)
        if result:
            return result

        # Strategy 2: Guest token + GraphQL (full data, may rate-limit)
        result = self._try_guest_graphql(tweet_id)
        if result:
            return result

        # Strategy 3: Syndication API (limited stats but reliable)
        result = self._try_syndication(tweet_id)
        if result:
            return result

        # Strategy 4: yt-dlp fallback (video only)
        result = self._try_ytdlp(url)
        if result:
            return result

        raise ValueError("Twitter: 所有提取策略均失败")

    def extract_user(self, screen_name: str) -> dict:
        """Extract user profile info via FxTwitter."""
        screen_name = screen_name.lstrip("@")
        if "twitter.com" in screen_name or "x.com" in screen_name:
            m = re.search(r'(?:twitter\.com|x\.com)/(\w+)', screen_name)
            if m:
                screen_name = m.group(1)
        try:
            client = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "clawkit/3.0"})
            resp = client.get(API_ENDPOINTS["twitter"]["fxtwitter_user"].format(screen_name=screen_name))
            _release_client(client)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            data = resp.json()
            u = data.get("user", {})
            return {
                "platform": "twitter", "type": "user_profile",
                "nickname": u.get("name", ""),
                "screen_name": u.get("screen_name", ""),
                "uid": u.get("id", ""),
                "bio": u.get("description", ""),
                "avatar": u.get("avatar_url", ""),
                "banner": u.get("banner_url", ""),
                "followers": u.get("followers", 0),
                "following": u.get("following", 0),
                "total_likes": u.get("likes", 0),
                "works_count": u.get("tweets", 0),
                "joined": u.get("joined", ""),
                "location": u.get("location", ""),
                "verified": u.get("verification", {}).get("verified", False) if isinstance(u.get("verification"), dict) else False,
            }
        except HANDLED_EXCEPTIONS as e:
            return {"error": str(e)}

# ─── 闲鱼/Goofish ─────────────────────────────────────────────────────────────

class GooFishExtractor(BaseExtractor):
    platform = "goofish"

    _MTOP_APPKEY = "12574478"

    def _get_mtop_token(self, client: httpx.Client) -> str:
        """Get _m_h5_tk token by calling a simple mtop API first."""
        ts = str(int(time.time() * 1000))
        # Call getTimestamp to trigger token cookie
        url = (f"https://h5api.m.goofish.com/h5/mtop.common.getTimestamp/1.0/"
               f"?jsv=2.7.4&appKey={self._MTOP_APPKEY}&t={ts}&sign=undefined"
               f"&api=mtop.common.getTimestamp&v=1.0&type=jsonp&dataType=jsonp&data=%7B%7D")
        resp = client.get(url)
        # Try to extract token from cookies
        token = client.cookies.get("_m_h5_tk", domain=".goofish.com")
        if token:
            return token.split("_")[0]
        # Try taobao domain
        token = client.cookies.get("_m_h5_tk", domain=".taobao.com")
        if token:
            return token.split("_")[0]
        # Also check all cookies
        for name, value in client.cookies.items():
            if name == "_m_h5_tk":
                return value.split("_")[0]
        return ""

    def _mtop_sign(self, token: str, timestamp: str, appkey: str, data: str) -> str:
        """Compute mtop sign = md5(token + & + timestamp + & + appkey + & + data)."""
        sign_str = f"{token}&{timestamp}&{appkey}&{data}"
        return hashlib.md5(sign_str.encode()).hexdigest()

    def search(self, keyword: str, count: int = 20) -> dict:
        """Search Goofish products by keyword. Uses web page scraping."""
        # Strategy 1: Try desktop web search page (SSR with embedded data)
        result = self._search_web(keyword, count)
        if result and result.get("results"):
            return result

        # Strategy 2: Try mobile web
        result = self._search_mobile(keyword, count)
        if result and result.get("results"):
            return result

        # Strategy 3: Try mtop API (may be blocked by baxia)
        result = self._search_mtop(keyword, count)
        if result and result.get("results"):
            return result

        return {
            "platform": "goofish", "type": "search", "keyword": keyword,
            "count": 0, "results": [],
            "message": "闲鱼搜索被反爬拦截。建议: 在 ~/.clawkit/cookies.json 中配置闲鱼 cookie。",
        }

    def _search_web(self, keyword: str, count: int) -> Optional[dict]:
        """Try desktop web search with SSR data extraction."""
        try:
            from urllib.parse import quote
            client = httpx.Client(
                follow_redirects=True, timeout=TIMEOUT,
                headers={
                    "User-Agent": DESKTOP_UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Referer": "https://www.goofish.com/",
                },
                cookies=_get_cookies("goofish"),
            )
            resp = client.get(f"https://www.goofish.com/search?q={quote(keyword)}")
            page = resp.text
            _release_client(client)

            if len(page) < 500:
                return None

            results = []

            # Try __NEXT_DATA__ (Next.js SSR)
            m = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.DOTALL)
            if m:
                try:
                    next_data = json.loads(m.group(1))
                    props = next_data.get("props", {}).get("pageProps", {})
                    items = (props.get("searchResult", {}).get("data", {}).get("resultList", [])
                             or props.get("resultList", [])
                             or props.get("data", {}).get("resultList", []))
                    for item in items[:count]:
                        item_data = item.get("data", item)
                        results.append(self._parse_item(item_data))
                    if results:
                        return {"platform": "goofish", "type": "search", "keyword": keyword,
                                "count": len(results), "results": results}
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"闲鱼 __NEXT_DATA__ 解析失败: {e}")

            # Try window.__INITIAL_STATE__ or window.__data__
            for pattern in [
                r'window\.__INITIAL_STATE__\s*=\s*(.*?);?\s*</script>',
                r'window\.__data__\s*=\s*(.*?);?\s*</script>',
                r'window\.rawData\s*=\s*(.*?);?\s*</script>',
            ]:
                m = re.search(pattern, page, re.DOTALL)
                if m:
                    try:
                        raw = m.group(1).strip().replace("undefined", "null")
                        state = json.loads(raw)
                        # Navigate to result list
                        items = self._find_items_in_json(state)
                        for item in items[:count]:
                            results.append(self._parse_item(item))
                        if results:
                            return {"platform": "goofish", "type": "search", "keyword": keyword,
                                    "count": len(results), "results": results}
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"闲鱼 state 解析失败: {e}")

            # Fallback: Extract from HTML meta/structured data
            items_from_html = self._extract_from_html(page)
            if items_from_html:
                return {"platform": "goofish", "type": "search", "keyword": keyword,
                        "count": len(items_from_html), "results": items_from_html[:count]}

            return None
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"闲鱼桌面搜索失败: {e}")
            return None

    def _search_mobile(self, keyword: str, count: int) -> Optional[dict]:
        """Try mobile web search."""
        try:
            from urllib.parse import quote
            client = httpx.Client(
                follow_redirects=True, timeout=TIMEOUT,
                headers={
                    "User-Agent": MOBILE_UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": "https://m.goofish.com/",
                },
                cookies=_get_cookies("goofish"),
            )
            resp = client.get(f"https://s.goofish.com/search?q={quote(keyword)}")
            page = resp.text
            _release_client(client)

            if len(page) < 500:
                return None

            results = []

            # Try embedded JSON
            for pattern in [
                r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                r'window\.__INITIAL_STATE__\s*=\s*(.*?);?\s*</script>',
                r'window\.rawData\s*=\s*(.*?);?\s*</script>',
                r'"resultList"\s*:\s*(\[.*?\])\s*[,}]',
            ]:
                m = re.search(pattern, page, re.DOTALL)
                if m:
                    try:
                        raw = m.group(1).strip().replace("undefined", "null")
                        data = json.loads(raw)
                        if isinstance(data, list):
                            items = data
                        elif isinstance(data, dict):
                            items = self._find_items_in_json(data)
                        else:
                            continue
                        for item in items[:count]:
                            parsed = self._parse_item(item)
                            if parsed.get("title"):
                                results.append(parsed)
                        if results:
                            return {"platform": "goofish", "type": "search", "keyword": keyword,
                                    "count": len(results), "results": results}
                    except (json.JSONDecodeError, KeyError):
                        continue

            # HTML extraction
            items_from_html = self._extract_from_html(page)
            if items_from_html:
                return {"platform": "goofish", "type": "search", "keyword": keyword,
                        "count": len(items_from_html), "results": items_from_html[:count]}

            return None
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"闲鱼移动搜索失败: {e}")
            return None

    def _search_mtop(self, keyword: str, count: int) -> Optional[dict]:
        """Try mtop API (usually blocked by baxia without browser env)."""
        try:
            from urllib.parse import quote
            client = httpx.Client(
                follow_redirects=True, timeout=TIMEOUT,
                headers={
                    "User-Agent": DESKTOP_UA,
                    "Origin": "https://www.goofish.com",
                    "Referer": "https://www.goofish.com/",
                },
                cookies=_get_cookies("goofish"),
            )
            token = self._get_mtop_token(client)
            if not token:
                _release_client(client)
                return None

            data = json.dumps({"keyword": keyword, "searchType": "item"}, separators=(',', ':'))
            ts = str(int(time.time() * 1000))
            sign = self._mtop_sign(token, ts, self._MTOP_APPKEY, data)

            api_url = (f"https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/"
                       f"?jsv=2.7.4&appKey={self._MTOP_APPKEY}&t={ts}&sign={sign}"
                       f"&api=mtop.taobao.idlemtopsearch.pc.search&v=1.0&data={quote(data)}")
            resp = client.get(api_url)
            _release_client(client)
            result = resp.json()

            ret = result.get("ret", [])
            if any("SUCCESS" in r for r in ret):
                items = result.get("data", {}).get("resultList", [])
                results = []
                for item in items[:count]:
                    item_data = item.get("data", item)
                    results.append(self._parse_item(item_data))
                return {"platform": "goofish", "type": "search", "keyword": keyword,
                        "count": len(results), "results": results}
            return None
        except HANDLED_EXCEPTIONS as e:
            logger.warning(f"闲鱼 mtop 搜索失败: {e}")
            return None

    def _find_items_in_json(self, data: dict, depth: int = 0) -> list:
        """Recursively find item list in nested JSON."""
        if depth > 5:
            return []
        if isinstance(data, dict):
            for key in ["resultList", "itemList", "items", "list", "data"]:
                val = data.get(key)
                if isinstance(val, list) and val:
                    # Check if items look like product data
                    first = val[0] if val else {}
                    if isinstance(first, dict) and any(k in first for k in ["title", "data", "item", "price"]):
                        return val
            # Recurse into dict values
            for val in data.values():
                if isinstance(val, (dict, list)):
                    found = self._find_items_in_json(val, depth + 1) if isinstance(val, dict) else []
                    if not found and isinstance(val, list):
                        # Check if this list contains product-like dicts
                        if val and isinstance(val[0], dict) and any(k in val[0] for k in ["title", "data", "price"]):
                            return val
                    if found:
                        return found
        return []

    def _parse_item(self, item: dict) -> dict:
        """Parse a single Goofish item from various data formats."""
        # Handle nested data structure
        if "data" in item and isinstance(item["data"], dict):
            item = item["data"]

        title = (item.get("title", "") or item.get("itemTitle", "")
                 or item.get("name", "") or item.get("desc", ""))
        # Clean HTML tags from title
        title = re.sub(r'<[^>]+>', '', title)

        price = (item.get("price", "") or item.get("itemPrice", "")
                 or item.get("soldPrice", "") or item.get("originalPrice", ""))
        if isinstance(price, (int, float)):
            price = f"{price:.0f}"

        seller = (item.get("sellerNick", "") or item.get("userName", "")
                  or item.get("nick", ""))
        if not seller:
            user_info = item.get("userInfo", {}) or item.get("seller", {})
            if isinstance(user_info, dict):
                seller = user_info.get("nickName", "") or user_info.get("nick", "")

        location = (item.get("area", "") or item.get("location", "")
                    or item.get("cityName", "") or item.get("itemArea", ""))

        images = []
        for img_key in ["picUrl", "imageUrl", "mainPic", "coverImg", "img"]:
            img = item.get(img_key, "")
            if img:
                if not img.startswith("http"):
                    img = "https:" + img
                images.append(img)
                break
        pic_list = item.get("picList", []) or item.get("images", []) or item.get("imageList", [])
        for p in pic_list[:5]:
            img_url = p if isinstance(p, str) else p.get("url", "")
            if img_url:
                if not img_url.startswith("http"):
                    img_url = "https:" + img_url
                images.append(img_url)

        item_id = str(item.get("itemId", "") or item.get("id", "") or item.get("nid", ""))
        url = ""
        if item_id:
            url = f"https://www.goofish.com/item?id={item_id}"

        return {
            "title": title,
            "price": str(price),
            "seller": seller,
            "location": location,
            "images": images[:5],
            "item_id": item_id,
            "url": url,
            "want_count": _safe_int(item.get("wantCount", 0) or item.get("soldCount", 0)),
        }

    def _extract_from_html(self, page: str) -> list:
        """Extract product data from HTML using meta tags and structured patterns."""
        results = []
        # Try to find product cards via common patterns
        # Look for JSON-LD
        for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.DOTALL):
            try:
                ld = json.loads(m.group(1))
                if isinstance(ld, dict) and ld.get("@type") == "Product":
                    results.append({
                        "title": ld.get("name", ""),
                        "price": str(ld.get("offers", {}).get("price", "")),
                        "images": [ld.get("image", "")] if ld.get("image") else [],
                        "seller": "", "location": "", "item_id": "", "url": "", "want_count": 0,
                    })
                elif isinstance(ld, list):
                    for item in ld:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            results.append({
                                "title": item.get("name", ""),
                                "price": str(item.get("offers", {}).get("price", "")),
                                "images": [item.get("image", "")] if item.get("image") else [],
                                "seller": "", "location": "", "item_id": "", "url": "", "want_count": 0,
                            })
            except json.JSONDecodeError:
                continue
        return results

    def extract(self, url: str) -> ExtractResult:
        """Extract single Goofish item page."""
        client = httpx.Client(
            follow_redirects=True, timeout=TIMEOUT,
            headers={"User-Agent": DESKTOP_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            cookies=_get_cookies("goofish"),
        )
        try:
            resp = _request_with_retry(client, "GET", url)
            page = resp.text

            # Try __NEXT_DATA__
            m = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.DOTALL)
            if m:
                try:
                    next_data = json.loads(m.group(1))
                    props = next_data.get("props", {}).get("pageProps", {})
                    item = props.get("itemInfo", {}) or props.get("data", {}).get("itemInfo", {}) or props
                    return self._item_to_result(item, url)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"闲鱼商品 __NEXT_DATA__ 解析失败: {e}")

            # Try window.__INITIAL_STATE__
            for pattern in [
                r'window\.__INITIAL_STATE__\s*=\s*(.*?);?\s*</script>',
                r'window\.__data__\s*=\s*(.*?);?\s*</script>',
            ]:
                m = re.search(pattern, page, re.DOTALL)
                if m:
                    try:
                        raw = m.group(1).strip().replace("undefined", "null")
                        state = json.loads(raw)
                        item = state.get("itemInfo", {}) or state
                        return self._item_to_result(item, url)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"闲鱼商品 state 解析失败: {e}")

            # Meta tags fallback
            title = ""
            m_title = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"', page)
            if m_title:
                title = html.unescape(m_title.group(1))
            desc = ""
            m_desc = re.search(r'<meta[^>]*(?:property="og:description"|name="description")[^>]*content="([^"]*)"', page)
            if m_desc:
                desc = html.unescape(m_desc.group(1))
            cover = ""
            m_img = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]*)"', page)
            if m_img:
                cover = m_img.group(1)

            return ExtractResult(
                platform="goofish", url=url,
                title=title, description=desc,
                cover_url=cover,
                media=[MediaItem(url=cover, type="image")] if cover else [],
            )
        finally:
            _release_client(client)

    def _item_to_result(self, item: dict, url: str) -> ExtractResult:
        """Convert Goofish item data to ExtractResult."""
        title = item.get("title", "") or item.get("itemTitle", "")
        desc = item.get("desc", "") or item.get("description", "") or title
        price = item.get("price", "") or item.get("itemPrice", "")

        seller_info = item.get("sellerInfo", {}) or item.get("userInfo", {})
        author = Author(
            nickname=seller_info.get("nickName", "") or seller_info.get("nick", "") or item.get("sellerNick", ""),
            uid=str(seller_info.get("userId", "") or seller_info.get("sellerId", "")),
        )
        avatar_url = seller_info.get("avatar", "") or seller_info.get("headUrl", "")

        location = item.get("area", "") or item.get("location", "") or item.get("cityName", "")

        media = []
        pic_list = item.get("picList", []) or item.get("images", []) or item.get("imageList", [])
        for p in pic_list:
            img_url = p if isinstance(p, str) else p.get("url", "")
            if img_url:
                if not img_url.startswith("http"):
                    img_url = "https:" + img_url
                media.append(MediaItem(url=img_url, type="image"))

        cover_url = media[0].url if media else ""
        item_id = str(item.get("itemId", "") or item.get("id", ""))

        return ExtractResult(
            platform="goofish", url=url,
            title=title, description=f"¥{price} - {desc}" if price else desc,
            author=author, avatar_url=avatar_url,
            media=media, raw_id=item_id,
            cover_url=cover_url, location=location,
            stats=Stats(collects=_safe_int(item.get("wantCount", 0))),
        )

# ─── 提取入口 ──────────────────────────────────────────────────────────────────

EXTRACTORS: dict[str, BaseExtractor] = {
    "douyin": DouyinExtractor(),
    "xiaohongshu": XiaohongshuExtractor(),
    "bilibili": BilibiliExtractor(),
    "weibo": WeiboExtractor(),
    "kuaishou": KuaishouExtractor(),
    "zhihu": ZhihuExtractor(),
    "youtube": YoutubeExtractor(),
    "twitter": TwitterExtractor(),
}

PLATFORM_NAMES = {
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "bilibili": "B站",
    "weibo": "微博",
    "kuaishou": "快手",
    "zhihu": "知乎",
    "youtube": "YouTube",
    "twitter": "Twitter/X",
}

def extract(url: str, comments: bool = False, comment_count: int = 20,
            related: bool = False, analyze: bool = False) -> ExtractResult:
    """统一提取入口"""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url 不能为空")
    urls = re.findall(r'https?://[^\s<>"\']+', url)
    if urls:
        url = urls[0]
    platform = detect_platform(url)
    extractor = EXTRACTORS[platform]
    result = extractor.extract(url)

    if comments and not result.comments and result.raw_id:
        max_pages = max(1, (comment_count + 19) // 20)
        if hasattr(extractor.fetch_comments, '__code__') and 'max_pages' in extractor.fetch_comments.__code__.co_varnames:
            result.comments = extractor.fetch_comments(result.raw_id, count=comment_count, max_pages=max_pages)
        else:
            result.comments = extractor.fetch_comments(result.raw_id, count=comment_count)

    if related and platform == "douyin" and result.raw_id:
        result.related = EXTRACTORS["douyin"].fetch_related(result.raw_id)

    if analyze:
        try:
            from .ocr import ocr_and_merge
            from .analyzer import analyze_content
            result.full_text = ocr_and_merge(result)
            stats_dict = asdict(result.stats) if hasattr(result, "stats") else {}
            result.analysis = analyze_content(result.full_text, result.platform, stats_dict)
        except Exception as e:
            logger.warning(f"内容分析跳过: {e}")
            if not result.full_text:
                result.full_text = result.description or ""
            if not result.analysis:
                result.analysis = {}

    return result

# ─── 批量处理 ──────────────────────────────────────────────────────────────────

def batch_extract(links_file: str, as_json: bool = False, output_dir: str = None,
                  fmt: str = "default") -> list[ExtractResult]:
    results = []
    errors = []
    with open(links_file) as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    total = len(urls)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    all_dicts = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{total}] 处理中... {url[:60]}", file=sys.stderr)
        try:
            result = extract(url)
            results.append(result)
            if output_dir:
                fname = f"{result.platform}_{result.raw_id or i}.json"
                with open(os.path.join(output_dir, fname), "w") as f:
                    json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
            if as_json:
                all_dicts.append(result.to_dict())
            elif fmt == "markdown":
                print(format_markdown(result))
            elif fmt == "brief":
                print(format_brief(result))
            else:
                print(format_result(result))
        except HANDLED_EXCEPTIONS as e:
            errors.append((url, str(e)))
            print(f"  ❌ 错误: {e}", file=sys.stderr)
            logger.warning(f"批量提取失败 [{url}]: {e}")

    # JSON batch output as array
    if as_json and all_dicts:
        print(json.dumps(all_dicts, ensure_ascii=False, indent=2))

    # Summary
    print(f"\n{'═'*40}", file=sys.stderr)
    print(f"  批量处理完成: 成功 {len(results)}/{total}", file=sys.stderr)
    if errors:
        print(f"  失败 {len(errors)} 个:", file=sys.stderr)
        for url, err in errors:
            print(f"    - {url[:50]}: {err[:50]}", file=sys.stderr)
    print(f"{'═'*40}", file=sys.stderr)

    return results

# ─── 下载 ──────────────────────────────────────────────────────────────────────

def download_media(result: ExtractResult, output_dir: str = ".") -> list[str]:
    if result.platform in ("youtube", "twitter"):
        os.makedirs(output_dir, exist_ok=True)
        try:
            out_tmpl = os.path.join(output_dir, f"{result.platform}_{result.raw_id}.%(ext)s")
            proc = subprocess.run(
                ["yt-dlp", "-o", out_tmpl, result.url],
                capture_output=True, text=True, timeout=300,
            )
            if proc.returncode == 0:
                import glob
                pattern = os.path.join(output_dir, f"{result.platform}_{result.raw_id}.*")
                files = glob.glob(pattern)
                for f in files:
                    print(f"  ✓ {os.path.basename(f)} ({os.path.getsize(f)/1024/1024:.1f} MB)")
                return files
        except HANDLED_EXCEPTIONS as e:
            print(f"  yt-dlp 下载失败: {e}", file=sys.stderr)
        return []

    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    client = _client()
    if result.platform == "bilibili":
        client.headers["Referer"] = "https://www.bilibili.com/"

    for i, m in enumerate(result.media):
        if not m.url:
            continue
        ext = "mp4" if m.type == "video" else "jpg"
        fname = f"{result.platform}_{result.raw_id}_{i}.{ext}"
        fpath = os.path.join(output_dir, fname)

        print(f"  下载: {fname} ...", end=" ", flush=True)
        try:
            resp = client.get(m.url, timeout=60)
            resp.raise_for_status()
            with open(fpath, "wb") as f:
                f.write(resp.content)
            size = os.path.getsize(fpath)
            print(f"✓ ({size/1024/1024:.1f} MB)")
            downloaded.append(fpath)
        except HANDLED_EXCEPTIONS as e:
            print(f"✗ ({e})")
            logger.warning(f"下载失败 platform={result.platform} url={m.url} file={fname}: {e}")

    _release_client(client)
    return downloaded

# ─── 格式化输出 ─────────────────────────────────────────────────────────────────

def format_result(r: ExtractResult) -> str:
    lines = []
    lines.append(f"{'═'*60}")
    lines.append(f"  平台: {PLATFORM_NAMES.get(r.platform, r.platform)}")
    lines.append(f"  ID:   {r.raw_id}")
    if r.create_time:
        lines.append(f"  发布: {r.create_time}")
    lines.append(f"{'─'*60}")
    lines.append(f"  标题: {r.title}")
    if r.description and r.description != r.title:
        desc = r.description[:200] + ("..." if len(r.description) > 200 else "")
        lines.append(f"  描述: {desc}")
    author_info = f"  作者: {r.author.nickname} (uid: {r.author.uid})"
    if r.author.followers:
        author_info += f" | 粉丝: {_fmt_num(r.author.followers)}"
    if r.author.following:
        author_info += f" | 关注: {_fmt_num(r.author.following)}"
    if r.author.total_likes:
        author_info += f" | 获赞: {_fmt_num(r.author.total_likes)}"
    lines.append(author_info)
    if r.author.bio:
        lines.append(f"  简介: {r.author.bio[:100]}")
    if r.duration:
        m, s = divmod(r.duration, 60)
        lines.append(f"  时长: {m}:{s:02d}")
    if r.note_type:
        lines.append(f"  类型: {'图文笔记' if r.note_type == 'image' else '视频笔记'}")
    if r.music:
        lines.append(f"  音乐: {r.music}")
    if r.location:
        lines.append(f"  位置: {r.location}")
    lines.append(f"{'─'*60}")

    stat_parts = []
    s = r.stats
    if s.views:      stat_parts.append(f"播放 {_fmt_num(s.views)}")
    if s.likes:      stat_parts.append(f"点赞 {_fmt_num(s.likes)}")
    if s.comments:   stat_parts.append(f"评论 {_fmt_num(s.comments)}")
    if s.collects:   stat_parts.append(f"收藏 {_fmt_num(s.collects)}")
    if s.shares:     stat_parts.append(f"分享 {_fmt_num(s.shares)}")
    if s.coins:      stat_parts.append(f"投币 {_fmt_num(s.coins)}")
    if s.danmaku:    stat_parts.append(f"弹幕 {_fmt_num(s.danmaku)}")
    if s.reposts:    stat_parts.append(f"转发 {_fmt_num(s.reposts)}")
    if stat_parts:
        lines.append(f"  互动: {' | '.join(stat_parts)}")

    if r.tags:
        lines.append(f"  标签: {'  '.join('#'+t for t in r.tags)}")

    lines.append(f"{'─'*60}")
    for i, m in enumerate(r.media):
        label = "🎬 视频" if m.type == "video" else "🖼  图片"
        url_display = m.url[:100] + ("..." if len(m.url) > 100 else "")
        lines.append(f"  {label} [{i}]: {url_display}")

    if r.cover_url:
        lines.append(f"  🖼  封面: {r.cover_url[:100]}...")

    if r.pages:
        lines.append(f"{'─'*60}")
        lines.append(f"  📑 分P ({len(r.pages)}P):")
        for p in r.pages[:10]:
            m, s = divmod(p.get('duration', 0), 60)
            lines.append(f"    P{p['page']}: {p['title']} ({m}:{s:02d})")

    if r.quality_list:
        labels = [q['label'] for q in r.quality_list]
        lines.append(f"  📺 可用清晰度: {' | '.join(labels)}")

    if r.related:
        lines.append(f"{'─'*60}")
        lines.append(f"  🔗 相关推荐:")
        for rv in r.related[:5]:
            lines.append(f"    {rv.get('author', '')}: {rv.get('desc', '')[:60]} (❤{_fmt_num(rv.get('likes', 0))})")

    if r.comments:
        lines.append(f"{'─'*60}")
        lines.append(f"  💬 评论 (前{len(r.comments)}条):")
        for c in r.comments[:5]:
            loc = f" [{c.ip_location}]" if c.ip_location else ""
            lines.append(f"    {c.author}{loc}: {c.content[:80]}" + (f" 👍{c.likes}" if c.likes else ""))
            for sc in (c.replies or [])[:2]:
                lines.append(f"      ↳ {sc.author}: {sc.content[:60]}")

    if r.analysis:
        lines.append(f"{'─'*60}")
        lines.append("  📊 内容解析")
        if r.analysis.get("content_type"):
            lines.append(f"  类型: {r.analysis.get('content_type')}")
        if r.analysis.get("key_points"):
            lines.append("  要点:")
            for p in r.analysis.get("key_points", [])[:5]:
                lines.append(f"    - {p}")
        if r.analysis.get("value_insight"):
            lines.append(f"  价值解读: {r.analysis.get('value_insight')}")
        if r.analysis.get("applicable_to"):
            lines.append(f"  适用人群: {r.analysis.get('applicable_to')}")
        if r.analysis.get("credibility"):
            lines.append(f"  可信度: {r.analysis.get('credibility')}")
        if r.analysis.get("summary"):
            lines.append(f"  总结: {r.analysis.get('summary')}")

    lines.append(f"{'═'*60}")
    return "\n".join(lines)

def format_markdown(r: ExtractResult) -> str:
    """Markdown format output suitable for notes."""
    lines = []
    pname = PLATFORM_NAMES.get(r.platform, r.platform)
    lines.append(f"## [{pname}] {r.title or r.description[:80]}")
    lines.append("")
    lines.append(f"- **作者**: {r.author.nickname}" + (f" (粉丝: {_fmt_num(r.author.followers)})" if r.author.followers else ""))
    if r.create_time:
        lines.append(f"- **发布时间**: {r.create_time}")
    if r.duration:
        m, s = divmod(r.duration, 60)
        lines.append(f"- **时长**: {m}:{s:02d}")
    if r.note_type:
        lines.append(f"- **类型**: {'图文笔记' if r.note_type == 'image' else '视频笔记'}")
    lines.append("")

    # Stats
    s = r.stats
    stat_parts = []
    if s.views:    stat_parts.append(f"▶ {_fmt_num(s.views)}")
    if s.likes:    stat_parts.append(f"❤ {_fmt_num(s.likes)}")
    if s.comments: stat_parts.append(f"💬 {_fmt_num(s.comments)}")
    if s.collects: stat_parts.append(f"⭐ {_fmt_num(s.collects)}")
    if s.shares:   stat_parts.append(f"🔄 {_fmt_num(s.shares)}")
    if s.coins:    stat_parts.append(f"🪙 {_fmt_num(s.coins)}")
    if stat_parts:
        lines.append(f"> {' · '.join(stat_parts)}")
        lines.append("")

    if r.description and r.description != r.title:
        lines.append(f"{r.description[:300]}")
        lines.append("")

    if r.tags:
        lines.append(f"**标签**: {' '.join('#'+t for t in r.tags)}")
        lines.append("")

    if r.pages:
        lines.append("### 分P列表")
        for p in r.pages:
            lines.append(f"- P{p['page']}: {p['title']} ({p['duration']//60}:{p['duration']%60:02d})")
        lines.append("")

    if r.media:
        lines.append("### 媒体")
        for i, m in enumerate(r.media):
            label = "视频" if m.type == "video" else "图片"
            lines.append(f"- [{label} {i}]({m.url[:200]})")
        lines.append("")

    if r.comments:
        lines.append(f"### 热门评论 (前{len(r.comments)}条)")
        for c in r.comments[:10]:
            loc = f" [{c.ip_location}]" if c.ip_location else ""
            likes = f" 👍{c.likes}" if c.likes else ""
            lines.append(f"- **{c.author}**{loc}: {c.content[:100]}{likes}")
            for sc in (c.replies or [])[:2]:
                lines.append(f"  - ↳ **{sc.author}**: {sc.content[:80]}")
        lines.append("")

    lines.append(f"🔗 [原文链接]({r.url})")
    return "\n".join(lines)

def format_brief(r: ExtractResult) -> str:
    """One-line brief summary."""
    pname = PLATFORM_NAMES.get(r.platform, r.platform)
    title = (r.title or r.description[:60]).replace("\n", " ")[:60]
    s = r.stats
    parts = [f"[{pname}]", f"@{r.author.nickname}", f'"{title}"']
    stats = []
    if s.views:  stats.append(f"▶{_fmt_num(s.views)}")
    if s.likes:  stats.append(f"❤{_fmt_num(s.likes)}")
    if s.comments: stats.append(f"💬{_fmt_num(s.comments)}")
    if stats:
        parts.append(" ".join(stats))
    return " | ".join(parts)

# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ClawKit v3.3 - 社交媒体内容提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
支持平台: 抖音 | 小红书 | B站 | 微博 | 快手 | 知乎 | YouTube | Twitter/X

示例:
  clawkit.py "https://v.douyin.com/xxx/"
  clawkit.py "https://www.bilibili.com/video/BVxxx" --json
  clawkit.py "https://youtu.be/xxx" --action download
  clawkit.py --batch links.txt --json --output results/
""",
    )
    parser.add_argument("url", nargs="?", help="分享链接")
    parser.add_argument("--action", "-a", choices=["info", "download", "full"],
                        default="info", help="info=仅信息, download=下载媒体, full=全部")
    parser.add_argument("--output", "-o", default="./downloads", help="下载/输出目录")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 格式输出")
    parser.add_argument("--comments", "-c", action="store_true", help="同时抓取评论")
    parser.add_argument("--comment-count", type=int, default=20, help="评论数量 (默认20, 最多100)")
    parser.add_argument("--batch", "-b", metavar="FILE", help="批量处理: 从文件读取链接列表")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--user", action="store_true", help="提取用户主页信息 (抖音/Twitter/B站)")
    parser.add_argument("--search", metavar="KEYWORD", help="搜索关键词 (抖音)")
    parser.add_argument("--related", action="store_true", help="抖音: 获取相关推荐")
    parser.add_argument("--analyze", action="store_true", help="启用 OCR + LLM 内容解析（可选，需要 GEMINI_API_KEY）")
    parser.add_argument("--markdown", "-m", action="store_true", help="Markdown 格式输出")
    parser.add_argument("--brief", action="store_true", help="极简一行输出")
    parser.add_argument("--trending", metavar="PLATFORM",
                        choices=["douyin", "bilibili", "weibo", "zhihu", "xiaohongshu"],
                        help="获取平台热门/热搜 (douyin|bilibili|weibo|zhihu|xiaohongshu)")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger("clawkit").setLevel(logging.DEBUG)

    # Trending mode
    if args.trending:
        try:
            extractor = EXTRACTORS[args.trending]
            results = _cached_trending(args.trending, extractor.trending)
            if args.json:
                print(json.dumps(results, ensure_ascii=False, indent=2))
            else:
                platform_name = PLATFORM_NAMES.get(args.trending, args.trending)
                print(f"\n🔥 {platform_name} 热门榜单\n{'─' * 50}")
                for item in results:
                    hot = f" ({item['hot_value']:,})" if item.get('hot_value') else ""
                    extra = f" - {item['author']}" if item.get('author') else ""
                    print(f"  {item['rank']:>2}. {item['title']}{hot}{extra}")
                    if item.get('url'):
                        print(f"      {item['url']}")
                print(f"\n共 {len(results)} 条")
        except HANDLED_EXCEPTIONS as e:
            print(f"❌ 热门获取失败: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # User profile mode (douyin / twitter / bilibili)
    if args.user and args.url:
        url_lower = args.url.lower()
        if any(k in url_lower for k in ["twitter.com", "x.com", "@"]):
            result = EXTRACTORS["twitter"].extract_user(args.url)
        elif any(k in url_lower for k in ["bilibili.com", "b23.tv"]) or args.url.isdigit():
            result = EXTRACTORS["bilibili"].extract_user(args.url)
        else:
            result = EXTRACTORS["douyin"].extract_user(args.url)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # Search mode (douyin)
    if args.search:
        result = EXTRACTORS["douyin"].search(args.search)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    fmt = "markdown" if args.markdown else ("brief" if args.brief else "default")

    if args.batch:
        batch_extract(args.batch, as_json=args.json,
                      output_dir=args.output if args.output != "./downloads" else None,
                      fmt=fmt)
        return

    if not args.url:
        parser.print_help()
        sys.exit(1)

    try:
        comment_count = min(args.comment_count, 100)
        result = extract(args.url, comments=args.comments,
                        comment_count=comment_count, related=args.related,
                        analyze=args.analyze)

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        elif args.markdown:
            print(format_markdown(result))
        elif args.brief:
            print(format_brief(result))
        else:
            print(format_result(result))

        if args.action in ("download", "full"):
            print("\n📥 下载媒体文件:")
            paths = download_media(result, args.output)
            if paths:
                print(f"\n✅ 下载完成，共 {len(paths)} 个文件 → {args.output}/")
            else:
                print("\n⚠️  没有可下载的媒体")

    except HANDLED_EXCEPTIONS as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
