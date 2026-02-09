import pytest

import clawkit


@pytest.mark.unit
class Describe_GoofishExtractor:
    def test_should_parse_item_to_result(self):
        """应将闲鱼 item 数据转换为标准结果。"""
        item = {"itemId": "1", "title": "宝贝", "price": "99", "sellerInfo": {"nickName": "卖家", "userId": "u1"}, "picList": ["//img"]}
        r = clawkit.GooFishExtractor()._item_to_result(item, "https://2.taobao.com/item.htm?id=1")
        assert r.title == "宝贝" and r.author.nickname == "卖家"

    def test_should_search_return_message_when_blocked(self, monkeypatch):
        """搜索被拦截时应返回提示信息。"""
        monkeypatch.setattr(clawkit.GooFishExtractor, "_search_web", lambda *a, **k: None)
        monkeypatch.setattr(clawkit.GooFishExtractor, "_search_mobile", lambda *a, **k: None)
        monkeypatch.setattr(clawkit.GooFishExtractor, "_search_mtop", lambda *a, **k: None)
        out = clawkit.GooFishExtractor().search("iphone")
        assert "message" in out and "cookie" in out["message"]

    def test_should_extract_return_empty_when_not_found(self, monkeypatch):
        """详情页找不到结构化数据时，应返回空壳结果而不是崩溃。"""
        class Resp:
            text = "<html></html>"
            url = "https://2.taobao.com/item.htm?id=1"

        monkeypatch.setattr(clawkit, "_request_with_retry", lambda *a, **k: Resp())
        monkeypatch.setattr(clawkit, "_release_client", lambda *a, **k: None)
        r = clawkit.GooFishExtractor().extract("https://2.taobao.com/item.htm?id=1")
        assert r.platform == "goofish"
