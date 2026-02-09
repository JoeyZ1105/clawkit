import sys
import types

import pytest

from clawkit.analyzer import analyze_content


@pytest.mark.unit
class Describe_analyze_content:
    def test_should_return_default_without_api_key(self, monkeypatch):
        monkeypatch.setattr("clawkit.analyzer._get_api_key", lambda: "")
        out = analyze_content("内容", "xiaohongshu", {"likes": 10})
        assert out["content_type"] == ""
        assert out["key_points"] == []

    def test_should_parse_structured_json_response(self, monkeypatch):
        monkeypatch.setattr("clawkit.analyzer._get_api_key", lambda: "k")

        class FakeResp:
            text = '{"content_type":"教程","key_points":["要点1"],"value_insight":"有价值","applicable_to":"管理者","credibility":"中等","summary":"一句话"}'

        class FakeClient:
            def __init__(self, api_key):
                self.models = self

            def generate_content(self, model, contents):
                return FakeResp()

        fake_google = types.ModuleType("google")
        fake_google.genai = types.SimpleNamespace(Client=FakeClient)
        monkeypatch.setitem(sys.modules, "google", fake_google)

        out = analyze_content("内容", "xiaohongshu", {})
        assert out["content_type"] == "教程"
        assert out["key_points"] == ["要点1"]
        assert out["summary"] == "一句话"
