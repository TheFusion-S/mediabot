"""Tiny .env editor used by the macOS scripts: `envtool.py get KEY` / `envtool.py set KEY VALUE`.

Works on the .env in the current directory, keeps comments and order, writes atomically with 0600.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

PATH = ".env"
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _read() -> list[str]:
    try:
        with open(PATH, encoding="utf-8") as fh:
            return fh.read().splitlines()
    except FileNotFoundError:
        return []


def get(key: str) -> str:
    value = ""
    for line in _read():
        m = re.match(rf"^\s*{re.escape(key)}\s*=(.*)$", line)
        if m:
            value = m.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
    return value


def set_(key: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise SystemExit("value must be a single line")
    lines, done = _read(), False
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(key)}\s*=", line):
            if not done:
                lines[i] = f"{key}={value}"
                done = True
            else:
                lines[i] = "# " + line  # duplicate definition: neutralise it
    if not done:
        lines.append(f"{key}={value}")
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "get" and KEY_RE.match(argv[1]):
        print(get(argv[1]))
        return 0
    if len(argv) == 3 and argv[0] == "set" and KEY_RE.match(argv[1]):
        set_(argv[1], argv[2])
        return 0
    print("usage: envtool.py get KEY | set KEY VALUE", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
