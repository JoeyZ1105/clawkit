from types import SimpleNamespace

import pytest

import clawkit
from clawkit.ocr import extract_video_text, ocr_and_merge


@pytest.mark.unit
class Describe_ocr_and_merge:
    def test_should_merge_description_and_ocr_text(self, monkeypatch):
        result = clawkit.ExtractResult(
            description="原始描述",
            media=[
                clawkit.MediaItem(url="https://img/1.jpg", type="image"),
                clawkit.MediaItem(url="https://img/2.jpg", type="image"),
            ],
        )

        monkeypatch.setattr("clawkit.ocr.ocr_images", lambda urls: ["图1文字", "图2文字"])
        monkeypatch.setattr("clawkit.ocr.extract_video_text", lambda url: "")

        merged = ocr_and_merge(result)
        assert "原始描述" in merged
        assert "图1文字" in merged
        assert "图2文字" in merged

    def test_should_fallback_to_description_when_no_image(self, monkeypatch):
        result = clawkit.ExtractResult(description="只有描述", media=[])
        monkeypatch.setattr("clawkit.ocr.ocr_images", lambda urls: [])
        monkeypatch.setattr("clawkit.ocr.extract_video_text", lambda url: "")
        assert ocr_and_merge(result) == "只有描述"

    def test_ocr_and_merge_with_video_media(self, monkeypatch):
        result = clawkit.ExtractResult(
            description="笔记描述",
            media=[
                clawkit.MediaItem(url="https://img/1.jpg", type="image"),
                clawkit.MediaItem(url="https://video/1.mp4", type="video"),
            ],
        )

        monkeypatch.setattr("clawkit.ocr.ocr_images", lambda urls: ["图片OCR文字"])
        monkeypatch.setattr("clawkit.ocr.extract_video_text", lambda url: "视频语音\n\n画面品牌: TEST")

        merged = ocr_and_merge(result)
        assert "笔记描述" in merged
        assert "图片OCR文字" in merged
        assert "视频语音" in merged
        assert "画面品牌: TEST" in merged


@pytest.mark.unit
def test_extract_video_text_with_mock(monkeypatch, tmp_path):
    monkeypatch.setattr("clawkit.ocr._ffmpeg_available", lambda: True)

    class _MockResp:
        def __init__(self, text=""):
            self.text = text

    class _MockModel:
        def __init__(self):
            self.calls = 0

        def generate_content(self, model, contents):
            self.calls += 1
            # First call = frame OCR (batch), second = audio transcription
            if self.calls == 1:
                return _MockResp("SOON AI游戏引擎 v1.0.2")
            return _MockResp("这是语音转写内容")

    mock_client = SimpleNamespace(models=_MockModel())
    monkeypatch.setattr("clawkit.ocr._get_client", lambda: mock_client)
    monkeypatch.setattr("clawkit.ocr._get_video_duration", lambda url: 20.0)

    def _fake_snapshot(video_url, seek_sec, output_path):
        with open(output_path, "wb") as f:
            f.write(b"fake-jpeg")
        return True

    def _fake_audio_clip(video_url, output_path, max_seconds=30):
        with open(output_path, "wb") as f:
            f.write(b"fake-audio")
        return True

    monkeypatch.setattr("clawkit.ocr._remote_snapshot", _fake_snapshot)
    monkeypatch.setattr("clawkit.ocr._remote_audio_clip", _fake_audio_clip)

    merged = extract_video_text("https://video/test.mp4")
    assert "语音转写" in merged
    assert "SOON" in merged
