import pytest

import clawkit


@pytest.mark.unit
class Describe_TwitterExtractor:
    def test_given_tweet_url_should_extract_text(self, monkeypatch):
        """给定推文链接时，应提取文本内容。"""
        fake = clawkit.ExtractResult(platform="twitter", title="hello", description="hello world")
        monkeypatch.setattr(clawkit.TwitterExtractor, "_try_fxtwitter", lambda *a, **k: fake)
        r = clawkit.TwitterExtractor().extract("https://x.com/a/status/1")
        assert r.description == "hello world"

    def test_given_tweet_url_should_extract_author(self, monkeypatch):
        """应提取作者昵称。"""
        fake = clawkit.ExtractResult(platform="twitter", author=clawkit.Author(nickname="alice"))
        monkeypatch.setattr(clawkit.TwitterExtractor, "_try_fxtwitter", lambda *a, **k: fake)
        r = clawkit.TwitterExtractor().extract("https://x.com/a/status/1")
        assert r.author.nickname == "alice"

    def test_given_tweet_url_should_extract_stats(self, monkeypatch):
        """应提取点赞等统计信息。"""
        fake = clawkit.ExtractResult(platform="twitter", stats=clawkit.Stats(likes=9, comments=2))
        monkeypatch.setattr(clawkit.TwitterExtractor, "_try_fxtwitter", lambda *a, **k: fake)
        r = clawkit.TwitterExtractor().extract("https://x.com/a/status/1")
        assert r.stats.likes == 9 and r.stats.comments == 2

    def test_given_tweet_url_should_extract_media(self, monkeypatch):
        """应提取媒体链接。"""
        fake = clawkit.ExtractResult(platform="twitter", media=[clawkit.MediaItem(url="https://m", type="image")])
        monkeypatch.setattr(clawkit.TwitterExtractor, "_try_fxtwitter", lambda *a, **k: fake)
        r = clawkit.TwitterExtractor().extract("https://x.com/a/status/1")
        assert r.media and r.media[0].url.startswith("http")
