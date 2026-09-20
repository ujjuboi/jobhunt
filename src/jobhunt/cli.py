"""
Command-line entry points for JobHunt (uv scripts).

  uv run jobhunt           -> launch the TUI (defined in __init__.py)
  uv run jobhunt-smoke     -> run the oMLX smoke test
  uv run jobhunt-test      -> run the pytest suite
  uv run jobhunt-check     -> smoke + test (dev convenience)
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def smoke() -> None:
    """Run the oMLX smoke test (reuses the root smoke.py)."""
    import runpy

    smoke_path = PROJECT_ROOT / "smoke.py"
    runpy.run_path(str(smoke_path), run_name="__main__")


def test() -> None:
    """Run the pytest test suite."""
    import pytest

    raise SystemExit(pytest.main(["-q"]))


def check() -> None:
    """Run the smoke test then the test suite."""
    try:
        smoke()
    except SystemExit as error:
        if error.code:
            print("\nSmoke test failed; skipping test suite", file=sys.stderr)
            raise
    test()


if __name__ == "__main__":
    raise SystemExit(smoke())