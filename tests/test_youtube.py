import json
import subprocess

import pytest

import clawkit


@pytest.mark.unit
class Describe_YoutubeExtractor:
    def test_should_extract_basic_fields(self, monkeypatch):
        """yt-dlp 返回 JSON 时应正确组装结果。"""
        payload = {"id": "x", "title": "yt", "description": "desc", "uploader": "u", "view_count": 1, "url": "https://v"}
        cp = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: cp)
        r = clawkit.YoutubeExtractor().extract("https://youtu.be/x")
        assert r.title == "yt" and r.author.nickname == "u"

    def test_should_raise_when_ytdlp_not_installed(self, monkeypatch):
        """未安装 yt-dlp 时应给出明确错误。"""
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        with pytest.raises(ValueError, match="yt-dlp"):
            clawkit.YoutubeExtractor().extract("https://youtu.be/x")

    def test_should_raise_when_ytdlp_fails(self, monkeypatch):
        """yt-dlp 执行失败时应抛出错误。"""
        cp = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: cp)
        with pytest.raises(ValueError, match="yt-dlp"):
            clawkit.YoutubeExtractor().extract("https://youtu.be/x")
