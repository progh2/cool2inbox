"""cool2inbox 진입점 — 아직 구현 전 (기획 단계).

개발 착수 후 여기서 단일 인스턴스 확인 → QApplication → 설정 로드 →
설정이 없으면 첫 실행 마법사 → 트레이 상주 순으로 이어진다. docs/PRD.md 5장 참고.
"""
from __future__ import annotations

import sys


def main() -> int:
    print("cool2inbox — 아직 개발 전입니다. README.md 와 docs/PRD.md 를 보세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
