"""트레이 아이콘 생성 — 펭귄 배달부 **임시** 버전.

v0.6(#21)에서 AI 로 만든 진짜 마스코트로 교체한다. 그때는 이 스크립트 대신
tools/prepare_penguin.py 가 원본 이미지를 같은 파일 이름으로 규격화한다.
즉 여기서 만드는 것은 파일 이름과 크기 규격을 미리 확정해 두기 위한 자리표시자다.

    python tools/make_icon.py

산출물: assets/penguin/{idle,working,paused,error,setup}.png (256px), assets/icon.png, assets/icon.ico
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
SIZE = 256

BLACK = (38, 42, 52, 255)
WHITE = (252, 252, 250, 255)
ORANGE = (247, 166, 60, 255)
BAG = (176, 120, 74, 255)
BAG_DARK = (140, 92, 56, 255)
BLUE = (74, 144, 226, 255)
RED = (219, 84, 76, 255)
GRAY = (150, 156, 168, 255)

STATES = ("idle", "working", "paused", "error", "setup")


def _penguin(d: ImageDraw.ImageDraw, s: int, *, eyes: str = "open", tilt: int = 0) -> None:
    """몸통·배·부리·눈·가방. tilt 는 고개 기울기(px)."""
    cx = s // 2
    # 몸통
    d.ellipse((s * 0.20, s * 0.24, s * 0.80, s * 0.94), fill=BLACK)
    # 머리
    d.ellipse((s * 0.26 + tilt, s * 0.14, s * 0.74 + tilt, s * 0.56), fill=BLACK)
    # 배
    d.ellipse((s * 0.32, s * 0.44, s * 0.68, s * 0.90), fill=WHITE)
    # 발
    d.ellipse((s * 0.30, s * 0.86, s * 0.46, s * 0.97), fill=ORANGE)
    d.ellipse((s * 0.54, s * 0.86, s * 0.70, s * 0.97), fill=ORANGE)
    # 눈
    ex1, ex2, ey = s * 0.41 + tilt, s * 0.59 + tilt, s * 0.32
    r = s * 0.045
    if eyes == "closed":
        for ex in (ex1, ex2):
            d.arc((ex - r, ey - r, ex + r, ey + r), 200, 340, fill=WHITE, width=max(2, s // 64))
    else:
        for ex in (ex1, ex2):
            d.ellipse((ex - r, ey - r, ex + r, ey + r), fill=WHITE)
            d.ellipse((ex - r * 0.45, ey - r * 0.3, ex + r * 0.45, ey + r * 0.6), fill=BLACK)
    # 부리
    d.polygon([(cx - s * 0.07 + tilt, s * 0.40), (cx + s * 0.07 + tilt, s * 0.40),
               (cx + tilt, s * 0.48)], fill=ORANGE)
    # 배달 가방 (어깨끈 + 가방)
    d.line((s * 0.34, s * 0.44, s * 0.70, s * 0.66), fill=BAG_DARK, width=max(3, s // 40))
    d.rounded_rectangle((s * 0.62, s * 0.58, s * 0.92, s * 0.82), radius=s // 22, fill=BAG)
    d.rounded_rectangle((s * 0.62, s * 0.58, s * 0.92, s * 0.66), radius=s // 30, fill=BAG_DARK)


def _badge(d: ImageDraw.ImageDraw, s: int, color, mark: str) -> None:
    """오른쪽 위 상태 배지."""
    x0, y0, x1, y1 = s * 0.60, s * 0.02, s * 0.98, s * 0.40
    d.ellipse((x0, y0, x1, y1), fill=color, outline=WHITE, width=max(2, s // 64))
    cx, cy, w = (x0 + x1) / 2, (y0 + y1) / 2, max(3, s // 42)
    if mark == "pause":
        d.rectangle((cx - s * 0.055, cy - s * 0.07, cx - s * 0.015, cy + s * 0.07), fill=WHITE)
        d.rectangle((cx + s * 0.015, cy - s * 0.07, cx + s * 0.055, cy + s * 0.07), fill=WHITE)
    elif mark == "bang":
        d.rectangle((cx - w / 2, cy - s * 0.075, cx + w / 2, cy + s * 0.025), fill=WHITE)
        d.ellipse((cx - w / 2, cy + s * 0.045, cx + w / 2, cy + s * 0.075 + w / 2), fill=WHITE)
    elif mark == "question":
        d.arc((cx - s * 0.055, cy - s * 0.085, cx + s * 0.055, cy + s * 0.015), 160, 20, fill=WHITE, width=w)
        d.line((cx, cy + s * 0.005, cx, cy + s * 0.035), fill=WHITE, width=w)
        d.ellipse((cx - w / 2, cy + s * 0.055, cx + w / 2, cy + s * 0.055 + w), fill=WHITE)
    elif mark == "arrow":                       # 배달 중 — 오른쪽 화살표
        d.line((cx - s * 0.055, cy, cx + s * 0.045, cy), fill=WHITE, width=w)
        d.polygon([(cx + s * 0.07, cy), (cx + s * 0.02, cy - s * 0.045),
                   (cx + s * 0.02, cy + s * 0.045)], fill=WHITE)


def make(state: str, s: int = SIZE) -> Image.Image:
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if state == "paused":
        _penguin(d, s, eyes="closed")
        _badge(d, s, GRAY, "pause")
    elif state == "working":
        _penguin(d, s)
        _badge(d, s, BLUE, "arrow")
    elif state == "error":
        _penguin(d, s, tilt=int(s * 0.03))      # 고개를 갸웃
        _badge(d, s, RED, "bang")
    elif state == "setup":
        _penguin(d, s)
        _badge(d, s, ORANGE, "question")
    else:
        _penguin(d, s)
    return im


def main() -> int:
    (OUT / "penguin").mkdir(parents=True, exist_ok=True)
    for st in STATES:
        p = OUT / "penguin" / f"{st}.png"
        make(st).save(p)
        print("생성:", p.relative_to(ROOT))
    idle = make("idle")
    idle.save(OUT / "icon.png")
    idle.save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print("생성:", (OUT / "icon.png").relative_to(ROOT), "·", (OUT / "icon.ico").relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
