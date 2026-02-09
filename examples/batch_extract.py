#!/usr/bin/env python3
# /// script
# dependencies = ["requests"]
# ///
"""
批量提取示例 - 从文件读取链接并提取信息

用法:
    uv run --with requests examples/batch_extract.py links.txt
    uv run --with requests examples/batch_extract.py links.txt --json --output results/
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clawkit import extract, format_result, download_media
import json
import argparse


def main():
    parser = argparse.ArgumentParser(description="批量提取社交媒体内容")
    parser.add_argument("file", help="链接文件（每行一个 URL）")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    parser.add_argument("--output", "-o", help="结果输出目录")
    parser.add_argument("--download", "-d", action="store_true", help="同时下载媒体")
    args = parser.parse_args()

    with open(args.file) as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if args.output:
        os.makedirs(args.output, exist_ok=True)

    print(f"📋 共 {len(urls)} 个链接\n", file=sys.stderr)

    results = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url[:60]}...", file=sys.stderr)
        try:
            result = extract(url)
            results.append(result)

            if args.json:
                print(json.dumps(result.to_dict(), ensure_ascii=False))
            else:
                print(format_result(result))

            if args.output:
                fname = f"{result.platform}_{result.raw_id or i}.json"
                with open(os.path.join(args.output, fname), "w") as f:
                    json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

            if args.download:
                download_media(result, args.output or "./downloads")

        except Exception as e:
            print(f"  ❌ {e}", file=sys.stderr)

    print(f"\n✅ 完成: {len(results)}/{len(urls)} 成功", file=sys.stderr)


if __name__ == "__main__":
    main()
