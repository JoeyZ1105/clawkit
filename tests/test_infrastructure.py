import pytest

import clawkit


@pytest.mark.unit
class Describe_safe_int:
    def test_given_integer_should_return_same(self):
        """给定整数时，应原样返回。"""
        assert clawkit._safe_int(123) == 123

    def test_given_numeric_string_should_convert(self):
        """给定数字字符串时，应正确转换为整数。"""
        assert clawkit._safe_int("456") == 456

    def test_given_none_should_return_zero(self):
        """给定 None 时，应返回 0。"""
        assert clawkit._safe_int(None) == 0

    def test_given_float_should_truncate(self):
        """给定浮点数时，应按 int 规则截断。"""
        assert clawkit._safe_int(12.9) == 12


@pytest.mark.unit
class Describe_fmt_num:
    def test_given_small_number_should_return_as_is(self):
        """小数字应直接返回字符串。"""
        assert clawkit._fmt_num(9999) == "9999"

    def test_given_ten_thousand_should_format_wan(self):
        """大于一万应格式化为万。"""
        assert clawkit._fmt_num(10000) == "1.0万"

    def test_given_hundred_million_should_format_yi(self):
        """大于一亿应格式化为亿。"""
        assert clawkit._fmt_num(100000000) == "1.0亿"


@pytest.mark.unit
class Describe_ts_to_iso:
    def test_given_unix_timestamp_should_return_iso(self):
        """给定 Unix 时间戳，应返回 ISO 时间。"""
        assert clawkit._ts_to_iso(1700000000).startswith("2023-")

    def test_given_zero_should_return_empty(self):
        """给定 0 应返回空字符串。"""
        assert clawkit._ts_to_iso(0) == ""


@pytest.mark.unit
class Describe_detect_platform:
    def test_given_douyin_url_should_detect_douyin(self):
        """抖音链接应识别为 douyin。"""
        assert clawkit.detect_platform("https://v.douyin.com/abc") == "douyin"

    def test_given_bilibili_url_should_detect_bilibili(self):
        """B站链接应识别为 bilibili。"""
        assert clawkit.detect_platform("https://www.bilibili.com/video/BV1xx") == "bilibili"

    def test_given_xhs_url_should_detect_xiaohongshu(self):
        """小红书链接应识别为 xiaohongshu。"""
        assert clawkit.detect_platform("https://www.xiaohongshu.com/explore/abc") == "xiaohongshu"

    def test_given_twitter_url_should_detect_twitter(self):
        """Twitter/X 链接应识别为 twitter。"""
        assert clawkit.detect_platform("https://x.com/a/status/1") == "twitter"

    def test_given_unknown_url_should_raise_error(self):
        """未知域名应抛出错误。"""
        with pytest.raises(ValueError):
            clawkit.detect_platform("https://example.org")


@pytest.mark.unit
class Describe_rate_limit:
    def test_should_enforce_minimum_interval(self, monkeypatch):
        """应在连续请求时触发最小间隔等待。"""
        sleeps = []
        monkeypatch.setattr(clawkit._time, "time", lambda: 0.1)
        monkeypatch.setattr(clawkit._time, "sleep", lambda s: sleeps.append(s))
        clawkit._last_request.clear()
        clawkit._last_request["t"] = 0.0
        clawkit._rate_limit("t", min_interval=0.5)
        assert sleeps and sleeps[0] == pytest.approx(0.4)


@pytest.mark.unit
class Describe_get_cookies:
    def test_given_no_cookie_file_should_return_empty(self, monkeypatch):
        """没有 cookie 时应返回空字典。"""
        clawkit._cookie_cache.clear()
        monkeypatch.setattr(clawkit, "_cookies_store", {})
        assert clawkit._get_cookies("weibo") == {}


@pytest.mark.unit
class Describe_release_client:
    def test_should_close_non_pooled_client(self):
        """非连接池客户端应被正常关闭且不递归。"""
        c = clawkit.httpx.Client()
        clawkit._release_client(c)
        assert c.is_closed


@pytest.mark.unit
class Describe_cached_trending:
    def test_should_cache_within_ttl(self, monkeypatch):
        """TTL 内应命中缓存，不重复拉取。"""
        clawkit._trending_cache.clear()
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return [calls["n"]]

        monkeypatch.setattr(clawkit.time, "time", lambda: 1000)
        assert clawkit._cached_trending("x", fetch) == [1]
        assert clawkit._cached_trending("x", fetch) == [1]
        assert calls["n"] == 1

    def test_should_refresh_after_ttl(self, monkeypatch):
        """TTL 过期后应重新拉取。"""
        clawkit._trending_cache.clear()
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return [calls["n"]]

        t = iter([1000, 1301])
        monkeypatch.setattr(clawkit.time, "time", lambda: next(t))
        clawkit._cached_trending("x", fetch)
        out = clawkit._cached_trending("x", fetch)
        assert out == [2]
