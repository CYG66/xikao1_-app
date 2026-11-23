"""Extract collection-error test files from a pytest collect-only log.

Parses the captured stdout/stderr of ``pytest --collect-only`` and writes one
test file path per line to the output file, for comparison against the
baseline collection-error allowlist. This helper only reports evidence; it
never changes the pytest exit code.

Usage
-----
    python scripts/ci/extract_collect_errors.py \
        --collect-stdout collect-stdout.txt --output collect-errors.txt
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

# Matches lines such as:
#   ERROR tests/test_foo.py
#   ERROR tests/test_foo.py - FileNotFoundError: ...
_ERROR_RE = re.compile(r"^ERROR\s+(?P<file>tests/[^\s:]+\.py)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract collect-error files.")
    parser.add_argument("--collect-stdout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    files: list[str] = []
    seen: set[str] = set()
    if args.collect_stdout.is_file():
        for line in args.collect_stdout.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _ERROR_RE.match(line.strip())
            if match:
                candidate = match.group("file")
                if candidate not in seen:
                    seen.add(candidate)
                    files.append(candidate)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(files) + ("\n" if files else ""), encoding="utf-8")
    print(f"collected {len(files)} collection-error file(s); wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
