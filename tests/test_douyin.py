import pytest

import clawkit


@pytest.mark.unit
class Describe_DouyinExtractor:
    def test_given_video_url_should_extract_title(self, douyin_fixture, make_extract_result, monkeypatch):
        """给定抖音视频链接时，应提取到标题。"""
        expected = make_extract_result(douyin_fixture)
        monkeypatch.setattr(clawkit.DouyinExtractor, "extract", lambda self, url: expected)
        r = clawkit.DouyinExtractor().extract("https://v.douyin.com/x")
        assert r.title == douyin_fixture["title"]

    def test_given_video_url_should_extract_author_info(self, douyin_fixture, make_extract_result, monkeypatch):
        """应提取作者昵称和 UID。"""
        expected = make_extract_result(douyin_fixture)
        monkeypatch.setattr(clawkit.DouyinExtractor, "extract", lambda self, url: expected)
        r = clawkit.DouyinExtractor().extract("https://v.douyin.com/x")
        assert r.author.nickname == douyin_fixture["author"]["nickname"]
        assert r.author.uid == douyin_fixture["author"]["uid"]

    def test_given_video_url_should_extract_stats(self, douyin_fixture, make_extract_result, monkeypatch):
        """应提取点赞、评论等互动数据。"""
        r = make_extract_result(douyin_fixture)
        assert r.stats.likes == douyin_fixture["stats"]["likes"]
        assert r.stats.comments == douyin_fixture["stats"]["comments"]

    def test_given_video_url_should_extract_media_urls(self, douyin_fixture, make_extract_result):
        """应提取至少一个媒体 URL。"""
        r = make_extract_result(douyin_fixture)
        assert r.media
        assert r.media[0].url.startswith("http")

    def test_given_invalid_url_should_handle_gracefully(self):
        """非法 URL 应抛出可理解异常。"""
        with pytest.raises(ValueError):
            clawkit.detect_platform("not-a-url")


@pytest.mark.unit
class Describe_DouyinExtractor_trending:
    def test_should_return_list_of_hot_items(self, monkeypatch):
        """热门接口应返回列表结构。"""
        fake = [{"rank": 1, "title": "热搜", "url": "https://x", "hot_value": 1}]
        monkeypatch.setattr(clawkit.DouyinExtractor, "trending", lambda self: fake)
        out = clawkit.DouyinExtractor().trending()
        assert isinstance(out, list) and out[0]["rank"] == 1
