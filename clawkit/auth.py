#!/usr/bin/env python3
# /// script
# dependencies = ["playwright", "httpx"]
# ///
"""
ClawKit 认证模块 - 浏览器登录 + Cookie 自动管理

用法:
    # 登录并保存 cookie
    python auth.py login weibo
    python auth.py login zhihu
    python auth.py login kuaishou
    python auth.py login xiaohongshu
    python auth.py login all

    # 查看 cookie 状态
    python auth.py status

    # 导出 cookie（供 clawkit.py 使用）
    python auth.py export [platform]
"""

import asyncio
import json
import sys
import time
import os
import fcntl
from datetime import datetime, timedelta
from pathlib import Path

# Platform login configurations
LOGIN_TIMEOUT = float(os.getenv("CLAWKIT_LOGIN_TIMEOUT", "300"))

PLATFORMS = {
    "weibo": {
        "name": "微博",
        "login_url": "https://passport.weibo.com/sso/signin",
        "success_cookies": ["SUB", "SUBP"],
        "success_url_contains": ["weibo.com/u/", "weibo.com/home", "my.weibo.com"],
        "domains": [".weibo.com", ".sina.com.cn", ".weibo.cn"],
        "expires_days": 30,
    },
    "zhihu": {
        "name": "知乎",
        "login_url": "https://www.zhihu.com/signin",
        "success_cookies": ["d_c0", "z_c0"],
        "success_url_contains": ["zhihu.com/follow", "zhihu.com/hot", "zhihu.com/"],
        "domains": [".zhihu.com"],
        "expires_days": 30,
    },
    "kuaishou": {
        "name": "快手",
        "login_url": "https://www.kuaishou.com",
        "success_cookies": ["userId", "didv", "kuaishou.server.web_st"],
        "success_url_contains": ["kuaishou.com"],
        "domains": [".kuaishou.com"],
        "expires_days": 14,
        "note": "可能需要点击页面上的登录按钮",
    },
    "xiaohongshu": {
        "name": "小红书",
        "login_url": "https://www.xiaohongshu.com",
        "success_cookies": ["web_session"],
        "success_url_contains": ["xiaohongshu.com"],
        "domains": [".xiaohongshu.com"],
        "expires_days": 30,
    },
}


class CookieManager:
    COOKIE_DIR = Path.home() / ".clawkit"
    COOKIE_FILE = COOKIE_DIR / "cookies.json"

    def __init__(self):
        self.COOKIE_DIR.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self.COOKIE_FILE.exists():
            try:
                with open(self.COOKIE_FILE, "r", encoding="utf-8") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    try:
                        return json.loads(f.read() or "{}")
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self):
        with open(self.COOKIE_FILE, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(self._data, ensure_ascii=False, indent=2))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    # ── public API ──────────────────────────────────────────

    async def login(self, platform: str):
        """Launch browser for user to login, detect success, save cookies."""
        cfg = PLATFORMS[platform]
        print(f"🌐 正在启动浏览器...")
        print(f"📱 请在浏览器中登录{cfg['name']}（扫码或输入验证码）")
        if cfg.get("note"):
            print(f"💡 提示: {cfg['note']}")

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
            page = await ctx.new_page()
            await page.goto(cfg["login_url"], wait_until="domcontentloaded")

            print("⏳ 等待登录完成...")

            # Poll for success cookies (max 5 min)
            deadline = time.time() + LOGIN_TIMEOUT
            success = False
            while time.time() < deadline:
                await asyncio.sleep(2)
                cookies = await ctx.cookies()
                cookie_names = {c["name"] for c in cookies}
                # Check if ANY of the success cookies appeared
                if any(sc in cookie_names for sc in cfg["success_cookies"]):
                    success = True
                    break

            if not success:
                print("❌ 登录超时（5分钟），请重试")
                await browser.close()
                return False

            # Gather all cookies for relevant domains
            all_cookies = await ctx.cookies()
            cookie_dict = {}
            raw_cookies = []
            for c in all_cookies:
                cookie_dict[c["name"]] = c["value"]
                raw_cookies.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c["domain"],
                    "path": c.get("path", "/"),
                    "expires": c.get("expires", -1),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                    "sameSite": c.get("sameSite", "Lax"),
                })

            ua = await page.evaluate("navigator.userAgent")
            await browser.close()

            now = datetime.now().isoformat(timespec="seconds")
            expires = (datetime.now() + timedelta(days=cfg["expires_days"])).isoformat(timespec="seconds")

            self._data[platform] = {
                "cookies": cookie_dict,
                "raw_cookies": raw_cookies,
                "updated_at": now,
                "expires_hint": expires,
                "user_agent": ua,
            }
            self._save()

            print(f"✅ {cfg['name']}登录成功！Cookie 已保存到 {self.COOKIE_FILE}")
            return True

    def get_cookies(self, platform: str) -> dict | None:
        """Return simple {name: value} cookie dict, or None."""
        entry = self._data.get(platform)
        if not entry:
            return None
        return entry.get("cookies")

    def get_raw_cookies(self, platform: str) -> list | None:
        """Return full cookie list (with domain/path/etc) for httpx or requests."""
        entry = self._data.get(platform)
        if not entry:
            return None
        return entry.get("raw_cookies")

    def get_user_agent(self, platform: str) -> str | None:
        entry = self._data.get(platform)
        if entry:
            return entry.get("user_agent")
        return None

    def is_authenticated(self, platform: str) -> bool:
        entry = self._data.get(platform)
        if not entry:
            return False
        expires = entry.get("expires_hint")
        if expires:
            try:
                if datetime.fromisoformat(expires) < datetime.now():
                    return False
            except ValueError:
                pass
        cfg = PLATFORMS.get(platform, {})
        cookies = entry.get("cookies", {})
        success_keys = cfg.get("success_cookies", [])
        return any(k in cookies for k in success_keys)

    def get_cookie_header(self, platform: str) -> str | None:
        """Return a Cookie header string ready for HTTP requests."""
        cookies = self.get_cookies(platform)
        if not cookies:
            return None
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    def status(self):
        """Print status table."""
        print("┌───────────┬──────┬─────────────────────┐")
        print("│ 平台      │ 状态 │ 更新时间            │")
        print("├───────────┼──────┼─────────────────────┤")
        for pid, cfg in PLATFORMS.items():
            name = cfg["name"].ljust(5, "\u3000") if len(cfg["name"]) < 4 else cfg["name"]
            authed = self.is_authenticated(pid)
            icon = "✅" if authed else "❌"
            entry = self._data.get(pid)
            if entry and entry.get("updated_at"):
                ts = entry["updated_at"]
                try:
                    dt = datetime.fromisoformat(ts)
                    delta = datetime.now() - dt
                    if delta.days > 0:
                        ago = f"{delta.days}d ago"
                    elif delta.seconds >= 3600:
                        ago = f"{delta.seconds // 3600}h ago"
                    else:
                        ago = f"{delta.seconds // 60}m ago"
                except ValueError:
                    ago = ts
            else:
                ago = "未登录"
            print(f"│ {cfg['name']:<7} │ {icon}  │ {ago:<19} │")
        print("└───────────┴──────┴─────────────────────┘")

    def export(self, platform: str | None = None):
        """Export cookies as JSON to stdout."""
        if platform:
            data = self._data.get(platform)
            if not data:
                print(f"❌ {platform} 未登录")
                return
            print(json.dumps({platform: data}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(self._data, ensure_ascii=False, indent=2))


# ── CLI ─────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cm = CookieManager()
    cmd = args[0]

    if cmd == "status":
        cm.status()
    elif cmd == "export":
        cm.export(args[1] if len(args) > 1 else None)
    elif cmd == "login":
        if len(args) < 2:
            print("用法: python auth.py login <weibo|zhihu|kuaishou|xiaohongshu|all>")
            return
        target = args[1]
        if target == "all":
            targets = list(PLATFORMS.keys())
        elif target in PLATFORMS:
            targets = [target]
        else:
            print(f"❌ 未知平台: {target}")
            print(f"支持: {', '.join(PLATFORMS.keys())}")
            return
        for t in targets:
            asyncio.run(cm.login(t))
    else:
        print(f"❌ 未知命令: {cmd}")
        print("支持: login, status, export")


if __name__ == "__main__":
    main()
