[English README](./README.md)

# ClawKit

[![CI](https://github.com/JoeyZ1105/clawkit/actions/workflows/test.yml/badge.svg)](https://github.com/JoeyZ1105/clawkit/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

本地优先的社交媒体内容提取工具。基础提取无需 API key。

ClawKit 可提取标准化元数据、媒体链接、评论（部分平台支持），并可选启用 OCR + LLM 内容解析。

## 支持平台

| 平台 | 链接格式 | 状态 | 评论 |
|------|---------|------|------|
| 抖音 | `v.douyin.com/xxx` | ✅ 完整 | ✅ 含子评论 |
| 小红书 | `xhslink.com/xxx`, `xiaohongshu.com/explore/xxx` | ✅ 完整 | ⚠️ 页面可能不含 |
| B站 | `bilibili.com/video/BVxxx` | ✅ 完整 | ✅ 含子评论 |
| 微博 | `weibo.com/xxx` | ⚠️ 需 cookie | - |
| 知乎 | `zhihu.com/question/xxx` | ⚠️ 需 cookie | - |
| 快手 | `v.kuaishou.com/xxx` | ⚠️ 反爬严格 | - |
| YouTube | `youtube.com/watch?v=xxx` | ✅ 需 yt-dlp | - |
| Twitter/X | `twitter.com/xxx/status/xxx`, `x.com/xxx/status/xxx` | ✅ 需 yt-dlp | - |
| 闲鱼 | `goofish.com/item/xxx` | ⚠️ 反爬严格 | - |

**说明:** ✅ = 稳定可用 | ⚠️ = 可能需要 cookie 或有限制

## 安装

**从 GitHub 安装（PyPI 发布前推荐）：**

```bash
pip install git+https://github.com/JoeyZ1105/clawkit.git
```

**从 PyPI 安装（发布后可用）：**

```bash
pip install clawkit
```

**开发安装：**

```bash
git clone https://github.com/JoeyZ1105/clawkit.git
cd clawkit
pip install -e ".[dev]"
```

## 快速开始

```bash
# 基础提取
clawkit "https://www.bilibili.com/video/BV1xx411c7mD"

# JSON 输出
clawkit "https://v.douyin.com/iYRAPA2w/" --json

# 包含评论
clawkit "https://www.bilibili.com/video/BV1xx411c7mD" --comments

# 批量处理
clawkit --batch links.txt --json --output results/

# 获取热门内容
clawkit --trending douyin
clawkit --trending bilibili
```

### 输出示例

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

## 可选依赖

| Extra | 安装命令 | 说明 |
|-------|---------|------|
| `auth` | `pip install "clawkit[auth]"` | Playwright 用于 cookie 提取 |
| `video` | `pip install "clawkit[video]"` | yt-dlp 用于 YouTube/Twitter 支持 |
| `analyze` | `pip install "clawkit[analyze]"` | Google Gemini 用于 OCR + 内容分析 |

**完整安装：**

```bash
pip install "clawkit[auth,video,analyze]"
```

## Cookie 配置

部分平台（微博、知乎、快手）需要 cookie 才能稳定提取。创建 `~/.clawkit/cookies.json`：

```json
{
  "weibo": {"SUB": "your_sub_cookie"},
  "zhihu": {"d_c0": "your_d_c0", "z_c0": "your_z_c0"},
  "kuaishou": {"didv": "your_cookie"}
}
```

## 负责任使用

ClawKit 设计用于**个人研究和教育目的**。使用时请注意：

- **遵守平台服务条款** — 不要用于大规模商业爬取
- **实施速率限制** — 避免给平台服务器造成过大压力；工具已内置延迟
- **禁止凭证收集** — 绝不使用 ClawKit 收集用户密码或会话令牌
- **尊重内容版权** — 下载的内容仍受原始版权保护
- **注意隐私保护** — 不要未经授权提取个人信息

维护者不对工具的滥用负责。

## 贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md) 了解开发设置和指南。

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
