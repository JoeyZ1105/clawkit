import pytest


@pytest.mark.unit
class Describe_XiaohongshuExtractor:
    def test_given_note_url_should_extract_title(self, xhs_fixture, make_extract_result):
        """给定小红书笔记链接时，应提取标题。"""
        r = make_extract_result(xhs_fixture)
        assert r.title == xhs_fixture["title"]

    def test_given_note_url_should_extract_author(self, xhs_fixture, make_extract_result):
        """应提取作者昵称。"""
        r = make_extract_result(xhs_fixture)
        assert r.author.nickname == xhs_fixture["author"]["nickname"]

    def test_given_note_url_should_extract_stats(self, xhs_fixture, make_extract_result):
        """应提取点赞与收藏等统计。"""
        r = make_extract_result(xhs_fixture)
        assert r.stats.likes == xhs_fixture["stats"]["likes"]
        assert r.stats.collects == xhs_fixture["stats"]["collects"]

    def test_given_note_url_should_extract_media(self, xhs_fixture, make_extract_result):
        """应提取图像或视频媒体。"""
        r = make_extract_result(xhs_fixture)
        assert len(r.media) >= 1
