import sys


def run() -> int:
    """Entry point for `python -m tankg` and the packaged executable: GUI unless CLI args are given."""
    if len(sys.argv) > 1 and sys.argv[1] != "gui":
        from .cli import main
    else:
        from .gui import main
    return main()


if __name__ == "__main__":
    sys.exit(run())
