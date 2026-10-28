"""Allow ``python -m spriteforge`` from the project root."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
