[中文说明 (README_CN)](./README_CN.md)

# ClawKit v3.3

> ClawKit is part of the OpenClaw ecosystem.

A free, local-first social media extractor. No API key required for basic extraction.

ClawKit extracts normalized metadata, media URLs/files, comments (where available), and can optionally run OCR + LLM analysis for image-heavy posts.

## Install

```bash
pip install clawkit
```

Or run without installing:

```bash
uvx clawkit "https://www.bilibili.com/video/BVxxx"
```

Legacy compatibility is still supported:

```bash
uv run clawkit.py "https://www.bilibili.com/video/BVxxx"
```

## Supported Platforms

- Douyin
- Xiaohongshu
- Bilibili
- Weibo
- Zhihu
- Kuaishou
- YouTube
- Twitter/X
- GooFish

## Quick Usage

```bash
# Basic extraction
clawkit "https://v.douyin.com/xxx/"

# JSON output
clawkit "https://www.bilibili.com/video/BVxxx" --json

# With comments
clawkit "https://v.douyin.com/xxx/" --comments

# Batch mode
clawkit --batch links.txt --json --output results/

# OCR + Analysis (optional)
clawkit "https://www.xiaohongshu.com/explore/xxx" --analyze
```

## Optional Dependencies

- `playwright` (auth helpers)
- `yt-dlp` (YouTube/Twitter media pipeline)
- `google-genai` (optional, for OCR and content analysis)

Install extras:

```bash
pip install "clawkit[auth,video,analyze]"
```

## CI

![CI](https://github.com/JoeyZ1105/clawkit/actions/workflows/test.yml/badge.svg)

## License

MIT
