import json
import os
import re


def _get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def _default_result() -> dict:
    return {
        "content_type": "",
        "key_points": [],
        "value_insight": "",
        "applicable_to": "",
        "credibility": "",
        "summary": "",
    }


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


def analyze_content(full_text: str, platform: str, stats: dict) -> dict:
    base = _default_result()
    if not full_text or not full_text.strip():
        return base

    api_key = _get_api_key()
    if not api_key:
        return base

    try:
        from google import genai
    except Exception:
        return base

    prompt = f"""
你是社交媒体内容分析助手。请基于下面的内容做“价值解读”，不是简单压缩。

要求：
1) 判断内容类型（教程/观点/带货/资讯/故事等，可组合）。
2) 提炼关键观点 key_points（强调真正有用的信息，不是机械摘要）。
3) 输出 value_insight：指出哪些内容有真实价值、哪些是包装，为什么有用或不够有用。
4) 输出 applicable_to：这类内容适合谁看。
5) 输出 credibility：评估可信度并说明依据（如是否有数据、案例、可验证方法）。
6) 输出 summary：一句话总结。

平台: {platform}
互动数据: {json.dumps(stats or {}, ensure_ascii=False)}

内容全文:
{full_text}

只输出 JSON，对象结构必须为：
{{
  "content_type": "",
  "key_points": [""],
  "value_insight": "",
  "applicable_to": "",
  "credibility": "",
  "summary": ""
}}
""".strip()

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        parsed = _extract_json(getattr(resp, "text", "") or "")
        if not isinstance(parsed, dict):
            return base

        out = {**base, **parsed}
        if not isinstance(out.get("key_points"), list):
            out["key_points"] = []
        return out
    except Exception:
        return base
