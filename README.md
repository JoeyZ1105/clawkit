[中文说明 (README_CN)](./README_CN.md)

# ClawKit

[![CI](https://github.com/JoeyZ1105/clawkit/actions/workflows/test.yml/badge.svg)](https://github.com/JoeyZ1105/clawkit/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local-first social media content extractor. No API key required for basic extraction.

ClawKit extracts normalized metadata, media URLs, comments (where available), and can optionally run OCR + LLM analysis for image-heavy posts.

## Supported Platforms

| Platform | Link Format | Status | Comments |
|----------|-------------|--------|----------|
| Douyin (抖音) | `v.douyin.com/xxx` | ✅ Full | ✅ With replies |
| Xiaohongshu (小红书) | `xhslink.com/xxx`, `xiaohongshu.com/explore/xxx` | ✅ Full | ⚠️ May not be in page |
| Bilibili (B站) | `bilibili.com/video/BVxxx` | ✅ Full | ✅ With replies |
| Weibo (微博) | `weibo.com/xxx` | ⚠️ Needs cookie | - |
| Zhihu (知乎) | `zhihu.com/question/xxx` | ⚠️ Needs cookie | - |
| Kuaishou (快手) | `v.kuaishou.com/xxx` | ⚠️ Strict anti-bot | - |
| YouTube | `youtube.com/watch?v=xxx` | ✅ Requires yt-dlp | - |
| Twitter/X | `twitter.com/xxx/status/xxx`, `x.com/xxx/status/xxx` | ✅ Requires yt-dlp | - |
| GooFish (闲鱼) | `goofish.com/item/xxx` | ⚠️ Strict anti-bot | - |

**Legend:** ✅ = Works reliably | ⚠️ = May require cookies or has limitations

## Installation

**From GitHub (recommended until PyPI release):**

```bash
pip install git+https://github.com/JoeyZ1105/clawkit.git
```

**From PyPI (when available):**

```bash
pip install clawkit
```

**Development install:**

```bash
git clone https://github.com/JoeyZ1105/clawkit.git
cd clawkit
pip install -e ".[dev]"
```

## Quick Start

```bash
# Basic extraction
clawkit "https://www.bilibili.com/video/BV1xx411c7mD"

# JSON output
clawkit "https://v.douyin.com/iYRAPA2w/" --json

# With comments
clawkit "https://www.bilibili.com/video/BV1xx411c7mD" --comments

# Batch mode
clawkit --batch links.txt --json --output results/

# Get trending content
clawkit --trending douyin
clawkit --trending bilibili
```

### Example Output

```
🎬 Bilibili | 【4K】最美satisfying视频合集
👤 满足强迫症的视频 | 粉丝: 50.2万
📊 👍 12.3万 | 💬 892 | ⭐ 2.1万 | 👀 156万
🔗 https://www.bilibili.com/video/BV1xx411c7mD
```

## Python API

```python
from clawkit import extract, ExtractResult

result = extract("https://v.douyin.com/iYRAPA2w/", comments=True)
print(result.title)
print(result.author.nickname)
print(result.stats.likes)
for comment in result.comments:
    print(f"{comment.author}: {comment.content}")
```

## Optional Dependencies

| Extra | Install | Description |
|-------|---------|-------------|
| `auth` | `pip install "clawkit[auth]"` | Playwright for cookie extraction |
| `video` | `pip install "clawkit[video]"` | yt-dlp for YouTube/Twitter support |
| `analyze` | `pip install "clawkit[analyze]"` | Google Gemini for OCR + content analysis |

**Full installation:**

```bash
pip install "clawkit[auth,video,analyze]"
```

## Cookie Configuration

Some platforms (Weibo, Zhihu, Kuaishou) require cookies for reliable extraction. Create `~/.clawkit/cookies.json`:

```json
{
  "weibo": {"SUB": "your_sub_cookie"},
  "zhihu": {"d_c0": "your_d_c0", "z_c0": "your_z_c0"},
  "kuaishou": {"didv": "your_cookie"}
}
```

## Responsible Use

ClawKit is designed for **personal research and educational purposes**. When using this tool:

- **Respect platform Terms of Service** — Do not use for commercial scraping at scale
- **Implement rate limiting** — Avoid overwhelming platform servers; the tool includes built-in delays
- **No credential harvesting** — Never use ClawKit to collect user passwords or session tokens
- **Respect content ownership** — Downloaded content remains subject to original copyright
- **Be mindful of privacy** — Do not extract personal information for unauthorized purposes

The maintainers are not responsible for misuse of this tool.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

MIT — see [LICENSE](LICENSE) for details.
