import pytest

import clawkit


@pytest.mark.unit
class Describe_WeiboExtractor:
    def test_should_extract_basic_fields(self):
        """应能从微博数据解析基础字段。"""
        data = {
            "text_raw": "测试微博",
            "user": {"screen_name": "作者", "id": 1},
            "reposts_count": 1,
            "comments_count": 2,
            "attitudes_count": 3,
        }
        r = clawkit.WeiboExtractor()._parse_weibo_data(data, "https://weibo.com/1", "123")
        assert r.title == "测试微博" and r.author.nickname == "作者"

    def test_should_return_trending_fixture_shape(self, weibo_trending_fixture):
        """微博热搜 fixture 应符合列表结构。"""
        assert isinstance(weibo_trending_fixture, list)
        assert "title" in weibo_trending_fixture[0]

    def test_should_raise_when_all_strategies_fail(self, monkeypatch):
        """当所有策略失败时，应抛出带 cookie 提示的错误。"""
        monkeypatch.setattr(clawkit, "_client", lambda *a, **k: object())
        monkeypatch.setattr(clawkit, "_request_with_retry", lambda *a, **k: type("R", (), {"url": "https://weibo.com/1/status/2"})())
        monkeypatch.setattr(clawkit.WeiboExtractor, "_try_ajax_api", lambda *a, **k: None)
        monkeypatch.setattr(clawkit.WeiboExtractor, "_try_mobile_detail", lambda *a, **k: None)
        monkeypatch.setattr(clawkit, "_release_client", lambda *a, **k: None)
        with pytest.raises(ValueError, match="cookie"):
            clawkit.WeiboExtractor().extract("https://weibo.com/1/status/2")
