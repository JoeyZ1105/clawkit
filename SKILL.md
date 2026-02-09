---
name: clawkit
description: "提取抖音、小红书、B站、微博、快手、知乎、YouTube、Twitter/X 等社交媒体内容（标题、描述、作者、互动数据、无水印媒体链接、评论）。支持分享链接自动识别平台。无需 API key，本地运行。"
version: v3
---

# clawkit v3

社交媒体内容提取工具。从分享链接提取结构化信息和无水印媒体下载地址。

## 用法

```bash
# 提取信息
uv run skills/clawkit/clawkit.py "链接"

# JSON 输出
uv run skills/clawkit/clawkit.py "链接" --json

# 下载媒体
uv run skills/clawkit/clawkit.py "链接" --action download --output ./media

# 带评论
uv run skills/clawkit/clawkit.py "链接" --comments

# OCR + LLM 解析（可选，需要 GEMINI_API_KEY / GOOGLE_API_KEY）
uv run skills/clawkit/clawkit.py "链接" --analyze

# 批量处理
uv run skills/clawkit/clawkit.py --batch links.txt --json --output results/

# 详细日志
uv run skills/clawkit/clawkit.py "链接" -v
```

## 支持平台

| 平台 | 链接格式 | 状态 | 评论 |
|------|---------|------|------|
| 抖音 | `v.douyin.com/xxx` | ✅ 完整 | ✅ |
| 小红书 | `xhslink.com/xxx` | ✅ 完整 | ⚠️ 页面可能不含 |
| B站 | `bilibili.com/video/BVxxx` | ✅ 完整 | ✅ 含子评论 |
| 微博 | `weibo.com/xxx` | ⚠️ 需cookie | - |
| 快手 | `v.kuaishou.com/xxx` | ⚠️ 反爬严格 | - |
| 知乎 | `zhihu.com/question/xxx` | ⚠️ 需cookie | - |
| YouTube | `youtube.com/watch?v=xxx` | ✅ 需yt-dlp | - |
| Twitter/X | `twitter.com/xxx/status/xxx` | ✅ 需yt-dlp | - |

## v2 新增字段

- `create_time` — 发布时间 (ISO格式)
- `duration` — 视频时长 (秒)
- `cover_url` — 封面图
- `avatar_url` — 作者头像
- `music` — BGM信息 (抖音)
- `location` — 地理位置
- `is_ad` — 是否广告
- `Comment.replies` — 子评论
- `Comment.ip_location` — IP属地
- `Comment.avatar` — 评论者头像

## Cookie 配置

微博、知乎、快手需要提供cookie才能正常使用。创建 `~/.clawkit/cookies.json`:

```json
{
  "weibo": {"SUB": "your_sub_cookie"},
  "zhihu": {"d_c0": "your_d_c0_cookie", "z_c0": "your_z_c0_cookie"},
  "kuaishou": {"didv": "your_cookie"}
}
```

## 依赖

- `httpx`（通过 inline script metadata 自动安装）
- `yt-dlp`（可选，用于 YouTube 和 Twitter）

## 程序调用

```python
from clawkit import extract, ExtractResult
result = extract("https://v.douyin.com/xxx/", comments=True)
print(result.title, result.author.nickname, result.stats.likes)
print(result.create_time, result.duration, result.music)
for c in result.comments:
    print(f"{c.author}: {c.content} ({c.ip_location})")
```

## 架构 (v3)

- `BaseExtractor` 基类，统一 `extract()` / `fetch_comments()` 接口
- `httpx.Client` 连接池 + 统一 15s 超时
- 指数退避重试 (最多3次)
- Cookie 管理 (`~/.clawkit/cookies.json`)
- 结构化日志 (logging.warning 替代 silent except)
