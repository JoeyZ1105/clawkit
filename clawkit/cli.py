from ._legacy import main as _legacy_main


def main():
    try:
        _legacy_main()
    except Exception as e:
        # CLI catches all errors and prints friendly message.
        print(f"ERROR: {e}")
        raise SystemExit(1)
