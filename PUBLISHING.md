# Publishing to PyPI

This document describes how to set up and publish ClawKit to PyPI using Trusted Publishing (OIDC).

## One-Time Setup (Repository Owner)

### 1. Create PyPI Account

If you don't have one, create an account at https://pypi.org/account/register/

### 2. Register the Package Name

Before publishing, verify that `clawkit` is available:
- Visit https://pypi.org/project/clawkit/ — should return 404 (not found)
- If taken, you'll need to choose a different name

### 3. Configure Trusted Publishing on PyPI

1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in:
   - **PyPI Project Name:** `clawkit`
   - **Owner:** `JoeyZ1105`
   - **Repository name:** `clawkit`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
4. Click "Add"

This creates a "pending publisher" that will be converted to a full publisher on the first successful upload.

### 4. Create GitHub Environment

1. Go to your repository Settings → Environments
2. Create a new environment named `pypi`
3. (Optional) Add protection rules:
   - Require reviewers for releases
   - Limit to `main` branch or tags

## Publishing a Release

### 1. Update Version

Edit `clawkit/__init__.py`:
```python
__version__ = "3.4.0"  # Bump appropriately
```

### 2. Update CHANGELOG

Add release notes to `CHANGELOG.md` following the existing format.

### 3. Commit and Tag

```bash
git add -A
git commit -m "chore: release v3.4.0"
git tag v3.4.0
git push origin main --tags
```

### 4. Monitor Release

1. Go to Actions tab → Release to PyPI workflow
2. Watch for successful completion
3. Verify at https://pypi.org/project/clawkit/

## Version Numbering

Follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (4.0.0): Breaking API changes
- **MINOR** (3.5.0): New features, backward compatible
- **PATCH** (3.4.1): Bug fixes, backward compatible

## Troubleshooting

### "Publisher not found" Error

The pending publisher on PyPI must exactly match:
- GitHub repository owner
- Repository name
- Workflow filename (`release.yml`)
- Environment name (`pypi`)

### Build Failures

Test locally before pushing:
```bash
pip install build twine
python -m build
twine check dist/*
```

### Post-Release Issues

If a release has critical bugs:
1. Yank the version on PyPI (doesn't delete, just hides from install)
2. Release a patch version with fixes

## Testing with TestPyPI (Optional)

For testing the release process without affecting production:

1. Set up a separate Trusted Publisher at https://test.pypi.org/
2. Create a `release-test.yml` workflow pointing to TestPyPI
3. Test the full flow before the real release
