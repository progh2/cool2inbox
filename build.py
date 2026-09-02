"""로컬 빌드 도구 (#22).

    python build.py            # 현재 OS 용 실행 파일을 만든다
    python build.py --clean    # build/ dist/ 를 먼저 지운다

실제 배포용 Windows exe 는 GitHub Actions 가 만든다 (.github/workflows/ci.yml).
이 스크립트는 손으로 확인해 보고 싶을 때 쓴다.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="build/ dist/ 를 먼저 지운다")
    args = ap.parse_args()

    if args.clean:
        for d in ("build", "dist"):
            shutil.rmtree(ROOT / d, ignore_errors=True)
            print(f"지움: {d}/")

    if not (ROOT / "assets" / "icon.ico").exists():
        print("아이콘이 없습니다. 먼저 실행하세요:")
        print("  python tools/prepare_penguin.py && python tools/make_icon.py")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller 가 없습니다:  pip install -r requirements-dev.txt")
        return 1

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(ROOT / "cool2inbox.spec")]
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode:
        return result.returncode

    out = ROOT / "dist"
    made = sorted(p for p in out.iterdir() if p.is_file()) if out.is_dir() else []
    for p in made:
        print(f"만들어짐: dist/{p.name}  ({p.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
