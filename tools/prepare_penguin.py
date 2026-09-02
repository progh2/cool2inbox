"""마스코트 스프라이트 시트 → 트레이 아이콘 규격 (#21).

    python tools/prepare_penguin.py

입력: `assets/penguin-src/sheet.png` — 펭귄 배달부 5종이 가로로 늘어선 한 장.
      (Higgsfield nano_banana_pro 로 생성. 프롬프트는 아래 PROMPT 에 남겨 둔다)
출력: `assets/penguin/{idle,working,paused,error,setup}.png` — 256px 투명 배경

원본은 4MB 가 넘고 저장소에 넣지 않는다(.gitignore). 다시 만들려면 PROMPT 로 재생성한 뒤
같은 자리에 두고 이 스크립트를 돌리면 된다.

배경 제거는 **모서리에서 시작하는 flood fill** 이다. 단순 흰색 임계값으로 지우면 펭귄의
크림색 배와 봉투까지 날아간다 — 배는 검은 윤곽선에 둘러싸여 있어 바깥에서 번져 들어오지 못한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "penguin-src" / "sheet.png"
OUT = ROOT / "assets" / "penguin"

# 왼쪽부터 차례대로 대응하는 상태 (src/ui/tray.py 의 AppState 와 파일명이 같아야 한다)
STATES = ("idle", "working", "paused", "error", "setup")

SIZE = 256
PAD_RATIO = 0.06          # 잘라낸 뒤 사방 여백 비율
KEY = (255, 0, 255)       # flood fill 로 칠할 색 (그림에 없는 색)
THRESH = 60               # 흰 배경과 옅은 그림자를 함께 지우기 위한 허용 오차
MIN_PANEL_WIDTH = 40      # 이보다 좁은 덩어리는 잡티로 본다

PROMPT = """A sprite sheet: exactly 5 panels in ONE horizontal row, evenly spaced with clear gaps,
on a pure flat white background. The SAME character in all 5 panels: an adorable chubby cartoon
penguin mail carrier mascot. Round body, dark charcoal-black head and back, creamy white oval belly,
bright orange beak and orange webbed feet, big friendly eyes. He wears a brown leather messenger
satchel bag on a diagonal shoulder strap. Flat vector illustration, bold clean outlines, minimal
flat shading, centered, full body, front-facing, identical proportions and colors in every panel.
Panel 1: standing calmly and smiling. Panel 2: running to the right holding a white envelope.
Panel 3: fast asleep standing up, eyes closed as curved lines. Panel 4: confused, head tilted,
wings in a small shrug. Panel 5: curious, holding up a large question mark sign.
No text, no words, no letters, no numbers, no watermark, no frames around panels."""


def cut_background(sheet: Image.Image) -> Image.Image:
    """모서리에서 flood fill 해 배경만 투명하게. 내부의 흰색(배·봉투)은 지키다."""
    rgb = sheet.convert("RGB")
    w, h = rgb.size
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for xy in seeds:
        if rgb.getpixel(xy) != KEY:
            ImageDraw.floodfill(rgb, xy, KEY, thresh=THRESH)
    out = rgb.convert("RGBA")
    px = out.load()
    for y in range(h):
        for x in range(w):
            if px[x, y][:3] == KEY:
                px[x, y] = (255, 255, 255, 0)
    return out


def panel_boxes(im: Image.Image) -> list[tuple[int, int, int, int]]:
    """불투명 픽셀이 있는 열을 묶어 패널 경계를 찾는다."""
    w, h = im.size
    alpha = im.getchannel("A")
    filled = [any(alpha.getpixel((x, y)) > 8 for y in range(0, h, 4)) for x in range(w)]

    boxes, start = [], None
    for x, on in enumerate(filled + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start >= MIN_PANEL_WIDTH:
                boxes.append((start, x))
            start = None

    out = []
    for x0, x1 in boxes:
        strip = im.crop((x0, 0, x1, h))
        bbox = strip.getbbox()
        out.append((x0, bbox[1], x1, bbox[3]) if bbox else (x0, 0, x1, h))
    return out


# 상태 배지 — 16px 트레이에서는 펭귄의 표정·자세가 뭉개져 구분이 안 된다.
# 색과 모양이 뚜렷한 배지를 얹으면 작은 크기에서도 상태를 알아볼 수 있다.
BADGES = {
    "working": ((74, 144, 226, 255), "arrow"),
    "paused": ((120, 128, 140, 255), "pause"),
    "error": ((219, 84, 76, 255), "bang"),
    "setup": ((240, 150, 40, 255), "question"),
}
BADGE_RATIO = 0.40        # 캔버스 대비 배지 지름


def add_badge(im: Image.Image, state: str) -> Image.Image:
    """오른쪽 아래에 상태 배지를 얹는다. idle 은 배지가 없다 (평상시가 기본)."""
    if state not in BADGES:
        return im
    color, mark = BADGES[state]
    s = im.width
    d = int(s * BADGE_RATIO)
    x0, y0 = s - d - int(s * 0.02), s - d - int(s * 0.02)
    x1, y1 = x0 + d, y0 + d

    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    ring = max(2, d // 12)
    g.ellipse((x0, y0, x1, y1), fill=color, outline=(255, 255, 255, 255), width=ring)

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w = max(2, d // 8)
    white = (255, 255, 255, 255)
    if mark == "pause":
        g.rectangle((cx - d * 0.17, cy - d * 0.19, cx - d * 0.05, cy + d * 0.19), fill=white)
        g.rectangle((cx + d * 0.05, cy - d * 0.19, cx + d * 0.17, cy + d * 0.19), fill=white)
    elif mark == "bang":
        g.rounded_rectangle((cx - w / 2, cy - d * 0.22, cx + w / 2, cy + d * 0.06),
                            radius=w / 2, fill=white)
        g.ellipse((cx - w / 2, cy + d * 0.12, cx + w / 2, cy + d * 0.12 + w), fill=white)
    elif mark == "question":
        g.arc((cx - d * 0.17, cy - d * 0.26, cx + d * 0.17, cy + d * 0.06), 170, 20,
              fill=white, width=w)
        g.line((cx + d * 0.005, cy + d * 0.02, cx + d * 0.005, cy + d * 0.10), fill=white, width=w)
        g.ellipse((cx - w / 2, cy + d * 0.16, cx + w / 2, cy + d * 0.16 + w), fill=white)
    elif mark == "arrow":
        g.line((cx - d * 0.18, cy, cx + d * 0.06, cy), fill=white, width=w)
        g.polygon([(cx + d * 0.22, cy), (cx + d * 0.02, cy - d * 0.15),
                   (cx + d * 0.02, cy + d * 0.15)], fill=white)

    return Image.alpha_composite(im, layer)


def square(im: Image.Image, size: int = SIZE) -> Image.Image:
    """비율을 지키며 정사각형 캔버스 가운데에 놓는다."""
    pad = int(max(im.size) * PAD_RATIO)
    side = max(im.size) + pad * 2
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> int:
    if not SRC.exists():
        print(f"원본이 없습니다: {SRC}\n프롬프트로 다시 만들어 같은 자리에 두세요:\n\n{PROMPT}")
        return 1

    sheet = Image.open(SRC).convert("RGBA")
    print(f"원본 {sheet.size[0]}×{sheet.size[1]}")
    cut = cut_background(sheet)
    boxes = panel_boxes(cut)
    print(f"패널 {len(boxes)}개 발견")
    if len(boxes) != len(STATES):
        print(f"⚠️ {len(STATES)}개를 기대했습니다. 경계: {[(b[0], b[2]) for b in boxes]}")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    for state, box in zip(STATES, boxes):
        img = add_badge(square(cut.crop(box)), state)
        path = OUT / f"{state}.png"
        img.save(path)
        print(f"  {state:<8} {box[2] - box[0]:>4}×{box[3] - box[1]:<4} → {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
