import pytest

import clawkit


@pytest.mark.unit
class Describe_ZhihuExtractor:
    def test_should_parse_article_from_initial_data(self):
        """应从 initialData 解析文章信息。"""
        data = {"initialState": {"entities": {"articles": {"10": {
            "title": "知乎文章", "content": "<p>正文</p>",
            "author": {"name": "作者", "urlToken": "u"},
            "voteupCount": 9, "commentCount": 2, "created": 1700000000
        }}}}}
        r = clawkit.ZhihuExtractor()._parse_initial_data(data, "article", "10", "https://zhuanlan.zhihu.com/p/10")
        assert r.title == "知乎文章" and r.author.nickname == "作者"

    def test_should_raise_cookie_hint_when_api_fails(self, monkeypatch):
        """API 失败时应抛出包含 cookie 提示的异常。"""
        monkeypatch.setattr(clawkit, "_client", lambda *a, **k: object())
        monkeypatch.setattr(clawkit, "_request_with_retry", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
        monkeypatch.setattr(clawkit, "_release_client", lambda *a, **k: None)
        with pytest.raises(ValueError, match="cookie"):
            clawkit.ZhihuExtractor()._try_api("article", "1", "https://z")

    def test_should_extract_question_stats(self):
        """应解析问题浏览量与回答数。"""
        data = {"initialState": {"entities": {"questions": {"20": {
            "title": "问题", "detail": "<p>详情</p>", "visitCount": 100, "answerCount": 5, "topics": []
        }}}}}
        r = clawkit.ZhihuExtractor()._parse_initial_data(data, "question", "20", "https://www.zhihu.com/question/20")
        assert r.stats.views == 100 and r.stats.comments == 5
