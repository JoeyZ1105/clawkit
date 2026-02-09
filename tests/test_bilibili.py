import pytest


@pytest.mark.unit
class Describe_BilibiliExtractor:
    def test_given_bv_url_should_extract_title(self, bilibili_fixture, make_extract_result):
        """给定 BV 链接时，应提取标题。"""
        r = make_extract_result(bilibili_fixture)
        assert r.title == bilibili_fixture["title"]

    def test_given_bv_url_should_extract_author(self, bilibili_fixture, make_extract_result):
        """应提取 UP 主信息。"""
        r = make_extract_result(bilibili_fixture)
        assert r.author.nickname == bilibili_fixture["author"]["nickname"]

    def test_given_bv_url_should_extract_stats(self, bilibili_fixture, make_extract_result):
        """应提取播放和点赞等统计。"""
        r = make_extract_result(bilibili_fixture)
        assert r.stats.views == bilibili_fixture["stats"]["views"]

    def test_given_bv_url_should_extract_video_urls(self, bilibili_fixture, make_extract_result):
        """应提取视频地址。"""
        r = make_extract_result(bilibili_fixture)
        videos = [m for m in r.media if m.type == "video"]
        assert videos and videos[0].url.startswith("http")


@pytest.mark.unit
class Describe_BilibiliExtractor_trending:
    def test_should_return_popular_videos(self, bilibili_trending_fixture):
        """热门榜结果应为非空列表。"""
        assert isinstance(bilibili_trending_fixture, list)
        assert bilibili_trending_fixture[0]["rank"] == 1
