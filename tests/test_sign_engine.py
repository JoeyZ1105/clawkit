import pytest

import sign_engine


@pytest.mark.unit
class Describe_sign_douyin:
    def test_should_return_non_empty_signature(self):
        """签名函数应返回非空字符串。"""
        sig = sign_engine.sign_douyin("aid=6383&aweme_id=123")
        assert isinstance(sig, str) and len(sig) > 10

    def test_should_be_deterministic_for_same_input(self):
        """相同输入多次签名时，输出格式应稳定（长度一致）。"""
        p = "aid=6383&aweme_id=123"
        s1 = sign_engine.sign_douyin(p)
        s2 = sign_engine.sign_douyin(p)
        assert isinstance(s1, str) and isinstance(s2, str)
        assert len(s1) == len(s2)


@pytest.mark.unit
class Describe_sign_xhs:
    def test_should_return_valid_signature_dict(self):
        """小红书签名应包含 x-s/x-t/x-s-common。"""
        out = sign_engine.sign_xiaohongshu("/api/sns/web/v1/feed", data={"a": 1}, a1="a", b1="b")
        assert set(["x-s", "x-t", "x-s-common"]).issubset(out.keys())
