# Contributing

Thanks for contributing to ClawKit.

## Development setup

```bash
git clone https://github.com/JoeyZ1105/clawkit.git
cd clawkit
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e . pytest
```

## Run tests

```bash
pytest tests/ -v
```

If you add network-related cases, mark them with `@pytest.mark.network`.

## Pull request checklist

- Keep public API backward compatible
- Add/adjust tests for behavior changes
- Ensure all tests pass locally
- Keep docs updated (`README.md`, `README_CN.md` if relevant)
