import os
import subprocess
import sys
from pathlib import Path

# Seeking into long-GOP H.264 (e.g. AVCHD .MTS) makes ffmpeg print "Missing reference
# picture" / "decode_slice_header error" on stderr. It's noise here: a frame that fails
# to decode is caught by the readers. OpenCV's ffmpeg plugin only honours this variable
# if it is in the environment when the process starts; setting it in-process (os.environ
# or SetEnvironmentVariableW) was tried and did not silence it. So relaunch once with it
# set. 8 = AV_LOG_FATAL. Set it yourself to choose another level; then no relaunch.
LOGLEVEL_VAR = "OPENCV_FFMPEG_LOGLEVEL"
PACKAGE_PARENT = Path(__file__).resolve().parent.parent


def _relaunch_quiet() -> int:
    env = dict(os.environ, **{LOGLEVEL_VAR: "8"})
    code = (f"import sys; sys.path.insert(0, {str(PACKAGE_PARENT)!r}); "
            "from mask_and_count.__main__ import main; sys.exit(main())")
    return subprocess.call([sys.executable, "-c", code, *sys.argv[1:]], env=env)


def main() -> int:
    if LOGLEVEL_VAR not in os.environ:
        return _relaunch_quiet()

    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

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
