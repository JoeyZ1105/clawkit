import os
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ._legacy import ExtractResult

OCR_PROMPT = "提取这张图片中的所有文字内容，保持原始格式和段落结构，只输出文字不要解释"
VIDEO_TRANSCRIBE_PROMPT = "请完整逐字转录这段音频中的所有语音内容，保持原始表述。"
VIDEO_FRAME_OCR_PROMPT = (
    "请提取这些视频截图中的所有可见文字，重点关注：工具名称、品牌名、网址、账号名、"
    "关键信息。合并所有截图的文字，去重后输出，不要解释。"
)


def _get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def _get_client():
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        from google import genai

        return genai.Client(api_key=api_key)
    except Exception:
        return None


def _guess_mime_type(content_type: str) -> str:
    if not content_type:
        return "image/jpeg"
    return content_type.split(";")[0].strip() or "image/jpeg"


def _dedupe_blocks(blocks: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for block in blocks:
        text = (block or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _get_video_duration(video_url: str) -> float:
    """用 ffprobe 获取视频时长（秒），失败返回 30.0 作为默认值"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_url],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 30.0


def _remote_snapshot(video_url: str, seek_sec: float, output_path: str) -> bool:
    """从远程视频 URL 直接截取指定时间点的一帧，不下载整个视频"""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(seek_sec), "-i", video_url,
             "-frames:v", "1", "-q:v", "2", output_path],
            check=True, capture_output=True, timeout=15,
        )
        return Path(output_path).exists() and Path(output_path).stat().st_size > 0
    except Exception:
        return False


def _remote_audio_clip(video_url: str, output_path: str, max_seconds: int = 30) -> bool:
    """从远程视频 URL 提取前 N 秒音频，不下载整个视频"""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_url, "-vn", "-t", str(max_seconds),
             "-acodec", "libopus", "-b:a", "32k", output_path],
            check=True, capture_output=True, timeout=30,
        )
        return Path(output_path).exists() and Path(output_path).stat().st_size > 0
    except Exception:
        return False


def ocr_images(image_urls: list[str]) -> list[str]:
    if not image_urls:
        return []

    client = _get_client()
    if not client:
        return [""] * len(image_urls)

    from google.genai import types

    outputs: list[str] = []
    for image_url in image_urls:
        try:
            resp = httpx.get(image_url, timeout=20)
            resp.raise_for_status()
            part = types.Part.from_bytes(
                data=resp.content,
                mime_type=_guess_mime_type(resp.headers.get("content-type", "")),
            )
            result = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[OCR_PROMPT, part],
            )
            outputs.append((getattr(result, "text", "") or "").strip())
        except Exception:
            outputs.append("")
    return outputs


def extract_video_text(video_url: str) -> str:
    """从视频中提取文字：远程截帧OCR + 语音转文字，不下载完整视频"""
    if not video_url:
        return ""

    if not _ffmpeg_available():
        warnings.warn("ffmpeg 未安装，跳过视频内容分析")
        return ""

    client = _get_client()
    if not client:
        warnings.warn("Gemini API 不可用，跳过视频内容分析")
        return ""

    from google.genai import types

    with tempfile.TemporaryDirectory(prefix="clawkit_video_") as tmpdir:
        # 1) 获取视频时长，计算截帧时间点
        duration = _get_video_duration(video_url)
        # 在 10%、35%、65%、90% 位置各截一帧（4帧，避免片头片尾）
        snap_points = [duration * p for p in (0.1, 0.35, 0.65, 0.9)]

        # 2) 远程截帧（不下载视频）
        frame_paths = []
        for i, sec in enumerate(snap_points):
            out = str(Path(tmpdir) / f"frame_{i}.jpg")
            if _remote_snapshot(video_url, sec, out):
                frame_paths.append(out)

        # 3) 批量 OCR：把所有帧合成一个请求，一次出结果
        frame_text = ""
        if frame_paths:
            try:
                parts = [VIDEO_FRAME_OCR_PROMPT]
                for fp in frame_paths:
                    parts.append(types.Part.from_bytes(
                        data=Path(fp).read_bytes(), mime_type="image/jpeg"
                    ))
                result = client.models.generate_content(
                    model="gemini-2.0-flash", contents=parts,
                )
                frame_text = (getattr(result, "text", "") or "").strip()
            except Exception:
                warnings.warn("视频关键帧OCR失败，已跳过画面文字部分")

        # 4) 远程提取音频 + 语音转文字（取前30秒）
        transcript_text = ""
        audio_path = str(Path(tmpdir) / "audio.ogg")
        if _remote_audio_clip(video_url, audio_path):
            try:
                audio_bytes = Path(audio_path).read_bytes()
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"),
                        VIDEO_TRANSCRIBE_PROMPT,
                    ],
                )
                transcript_text = (getattr(response, "text", "") or "").strip()
            except Exception:
                warnings.warn("视频语音转文字失败，已跳过语音部分")

        merged = _dedupe_blocks([transcript_text, frame_text])
        return "\n\n".join(merged).strip()


def ocr_and_merge(result: "ExtractResult") -> str:
    description = (result.description or "").strip()
    media = result.media or []

    image_urls = [m.url for m in media if getattr(m, "type", "") == "image" and getattr(m, "url", "")]
    video_urls = [m.url for m in media if getattr(m, "type", "") == "video" and getattr(m, "url", "")]

    ocr_texts = [t.strip() for t in ocr_images(image_urls) if t and t.strip()]
    video_texts = [t.strip() for t in (extract_video_text(url) for url in video_urls) if t and t.strip()]

    chunks = _dedupe_blocks([description, *ocr_texts, *video_texts])
    return "\n\n".join(chunks).strip()
