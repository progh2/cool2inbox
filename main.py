"""cool2inbox 진입점.

단일 인스턴스 확인 → QApplication → 설정 로드 → 트레이 상주.
설정이 없으면 첫 실행 마법사를 띄운다 (#17 에서 붙인다).
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from src.logging_setup import setup_logging

    setup_logging()

    import logging

    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from src import config as cfg
    from src import single_instance as si
    from src.app import AppController

    log = logging.getLogger("cool2inbox")

    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("cool2inbox")
    app.setQuitOnLastWindowClosed(False)     # 창을 닫아도 트레이에 남는다

    holder: dict = {}

    def on_second_instance() -> None:
        tray = holder.get("tray")
        if tray is not None:
            tray.notify("cool2inbox", "이미 실행 중입니다. 트레이 아이콘을 확인하세요.")

    server = si.acquire(on_show=on_second_instance)
    if server is None:
        log.info("이미 실행 중이라 종료합니다.")
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("이 환경에는 시스템 트레이가 없습니다. 아이콘이 보이지 않을 수 있습니다.")

    controller = AppController(app, config=cfg.Config.load())
    controller.instance_server = server
    holder["tray"] = controller.tray
    controller.tray.show()

    log.info("cool2inbox 시작")
    try:
        return app.exec()
    finally:
        server.close()


if __name__ == "__main__":
    sys.exit(main())
