#!/usr/bin/env python3
"""Convert a PNG icon to RGBA so Tauri can consume it reliably."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python3 scripts/convert_tauri_icon.py <icon.png>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1]).expanduser().resolve()
    if not path.exists():
        print(f"No existe: {path}", file=sys.stderr)
        return 1

    image = Image.open(path).convert("RGBA")
    image.save(path)
    print(f"converted {path} -> mode={image.mode} size={image.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
