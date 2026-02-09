import pytest

import clawkit


@pytest.mark.unit
class Describe_KuaishouExtractor:
    def test_should_return_result_when_mobile_success(self, monkeypatch):
        """移动端成功时应直接返回结果。"""
        fake = clawkit.ExtractResult(platform="kuaishou", title="k")
        monkeypatch.setattr(clawkit.KuaishouExtractor, "_try_mobile", lambda *a, **k: fake)
        r = clawkit.KuaishouExtractor().extract("https://www.kuaishou.com/short-video/1")
        assert r.title == "k"

    def test_should_raise_cookie_hint_when_empty_result(self, monkeypatch):
        """结果为空且被反爬时，应提示配置 cookie。"""
        empty = clawkit.ExtractResult(platform="kuaishou")
        monkeypatch.setattr(clawkit.KuaishouExtractor, "_try_mobile", lambda *a, **k: None)
        monkeypatch.setattr(clawkit.KuaishouExtractor, "_try_pc", lambda *a, **k: empty)
        with pytest.raises(ValueError, match="cookie"):
            clawkit.KuaishouExtractor().extract("https://www.kuaishou.com/short-video/1")

    def test_should_fallback_to_pc(self, monkeypatch):
        """移动端失败时应回退到 PC 解析。"""
        fake = clawkit.ExtractResult(platform="kuaishou", title="pc")
        monkeypatch.setattr(clawkit.KuaishouExtractor, "_try_mobile", lambda *a, **k: None)
        monkeypatch.setattr(clawkit.KuaishouExtractor, "_try_pc", lambda *a, **k: fake)
        r = clawkit.KuaishouExtractor().extract("https://www.kuaishou.com/short-video/1")
        assert r.title == "pc"
