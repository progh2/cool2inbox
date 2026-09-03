"""cool2inbox 진입점.

단일 인스턴스 확인 → QApplication → 설정 로드 → 트레이 상주.
설정이 없으면 첫 실행 마법사를 띄운다 (#17 에서 붙인다).
"""
from __future__ import annotations

import sys


def _detach_console() -> None:
    """얼린 앱이 콘솔에 붙어 실행됐으면 그 콘솔을 떼어낸다 (검은 창 방지).

    GUI 서브시스템으로 빌드해도, 콘솔을 가진 부모(터미널·일부 자동 실행·작업 스케줄러)가
    띄우면 그 콘솔을 물려받아 창이 보인다. FreeConsole 로 분리하면 우리가 마지막 사용자일 때
    창이 닫힌다. 콘솔이 없으면 아무 일도 하지 않는다.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        if ctypes.windll.kernel32.GetConsoleWindow():
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    _detach_console()

    from src.logging_setup import setup_logging

    # 얼린 앱은 콘솔이 없으므로 stderr 로그를 끈다 (회전 파일에는 계속 남는다).
    setup_logging(to_stderr=not getattr(sys, "frozen", False))

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
    controller.prompt_setup_if_needed()

    log.info("cool2inbox 시작")
    try:
        return app.exec()
    finally:
        server.close()


if __name__ == "__main__":
    sys.exit(main())
