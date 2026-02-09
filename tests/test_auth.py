from pathlib import Path

import pytest

import auth


@pytest.mark.unit
class Describe_CookieManager:
    def test_should_create_cookie_dir(self, monkeypatch, tmp_path):
        """初始化时应创建 cookie 目录。"""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cm = auth.CookieManager()
        assert cm.COOKIE_DIR.exists()

    def test_should_save_and_load_cookies(self, monkeypatch, tmp_path):
        """保存后应可再次读取 cookies。"""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cm = auth.CookieManager()
        cm._data["weibo"] = {"cookies": {"SUB": "abc"}}
        cm._save()
        cm2 = auth.CookieManager()
        assert cm2.get_cookies("weibo") == {"SUB": "abc"}

    def test_should_handle_missing_file(self, monkeypatch, tmp_path):
        """cookie 文件不存在时应安全返回空。"""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cm = auth.CookieManager()
        assert cm.get_cookies("zhihu") is None
