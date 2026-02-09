[English README](./README.md)

# ClawKit v3.3 — 社交媒体内容提取工具

> ClawKit is part of the OpenClaw ecosystem.

免费、本地运行（基础提取无需 API key）。从社交媒体链接提取元数据、媒体文件和评论，并可选启用 OCR + LLM 内容解析。

## 安装

```bash
pip install clawkit
# 或
uvx clawkit "链接"
```

兼容旧用法：

```bash
uv run clawkit.py "链接"
```

## 支持平台

- 抖音、小红书、B站、微博、快手、知乎、YouTube、Twitter/X、闲鱼

## 常用命令

```bash
clawkit "https://www.bilibili.com/video/BVxxx" --json
clawkit "https://v.douyin.com/xxx/" --comments
clawkit --batch links.txt --json --output results/
clawkit "https://www.xiaohongshu.com/explore/xxx" --analyze
```

## Cookie 配置

微博、知乎、快手建议配置 `~/.clawkit/cookies.json` 以提高成功率。

## 可选依赖

- `google-genai`：用于 OCR 与内容解析（`--analyze`）

安装示例：

```bash
pip install "clawkit[analyze]"
```

## 许可证

MIT
