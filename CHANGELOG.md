# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.4.0] - 2026-10-22

### Added
- PyPI packaging with Trusted Publishing release workflow
- Comprehensive pyproject.toml metadata (keywords, classifiers, URLs)
- SECURITY.md with vulnerability reporting guidelines
- GitHub issue templates (bug report, feature request)
- Pull request template
- PUBLISHING.md with PyPI setup instructions
- "Responsible Use" section in README

### Changed
- Single-sourced version number from `clawkit/__init__.py`
- Rewrote README.md and README_CN.md with accurate install instructions
- Improved platform status table with honest limitations
- Tests now skip gracefully when optional dependencies are missing

### Fixed
- `test_extract_video_text_with_mock` now skips when google-genai not installed
- CLI version display now uses dynamic version

## [3.3.1] - 2026-02-09

### Changed
- Video analysis 3x faster using remote snapshot instead of full download

## [3.3.0] - 2026-02-01

### Added
- OCR + LLM content analysis with `--analyze` flag
- Video frame OCR and audio transcription
- GooFish (闲鱼) platform support

### Changed
- Improved error handling across all extractors

## [3.2.0] - 2026-01-15

### Added
- Trending content support (`--trending <platform>`)
- Batch processing mode (`--batch`)
- Comment extraction with replies

### Changed
- Unified HTTP client with connection pooling
- Rate limiting with exponential backoff

## [3.0.0] - 2025-12-01

### Added
- Complete rewrite with `BaseExtractor` architecture
- Structured data models (ExtractResult, Author, Stats, etc.)
- Cookie management system
- Support for 9 platforms

### Changed
- Migrated from ad-hoc scripts to proper Python package

[Unreleased]: https://github.com/JoeyZ1105/clawkit/compare/v3.4.0...HEAD
[3.4.0]: https://github.com/JoeyZ1105/clawkit/compare/v3.3.1...v3.4.0
[3.3.1]: https://github.com/JoeyZ1105/clawkit/compare/v3.3.0...v3.3.1
[3.3.0]: https://github.com/JoeyZ1105/clawkit/compare/v3.2.0...v3.3.0
[3.2.0]: https://github.com/JoeyZ1105/clawkit/compare/v3.0.0...v3.2.0
[3.0.0]: https://github.com/JoeyZ1105/clawkit/releases/tag/v3.0.0
