"""앱 아이콘 생성 (#21).

    python tools/prepare_penguin.py && python tools/make_icon.py

`assets/penguin/idle.png` 을 앱 아이콘으로 삼아 `assets/icon.png` 과 다중 크기 `assets/icon.ico`
를 만든다. Windows 는 작업 표시줄·트레이·바로가기에서 각각 다른 크기를 꺼내 쓰므로 16~256 을
모두 넣어 둔다 (하나만 넣으면 축소 품질이 나쁘다).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "penguin" / "idle.png"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    if not SOURCE.exists():
        print(f"먼저 tools/prepare_penguin.py 를 실행하세요 — {SOURCE} 가 없습니다.")
        return 1
    im = Image.open(SOURCE).convert("RGBA")
    im.save(ASSETS / "icon.png")
    im.save(ASSETS / "icon.ico", sizes=ICO_SIZES)
    print(f"생성: assets/icon.png ({im.width}px), assets/icon.ico ({len(ICO_SIZES)}개 크기)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
