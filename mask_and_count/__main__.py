import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    # Identity for QSettings (last folder etc.); on Windows this lands in the registry
    # under HKCU/Software/antscihub/mask-and-count.
    app.setOrganizationName("antscihub")
    app.setApplicationName("mask-and-count")
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    window = MainWindow(folder)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
