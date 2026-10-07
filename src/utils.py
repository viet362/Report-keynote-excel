import os
import sys

def get_resource_path(relative_path: str) -> str:
    """
    Finds the absolute path to a bundled or project resource file.
    Works seamlessly whether running from source (.py), PyInstaller onedir, or macOS .app bundle.
    """
    candidates = []

    # 1. PyInstaller _MEIPASS extraction directory
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, relative_path))

    # 2. Inside macOS .app bundle (Contents/Resources or Contents/MacOS)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.abspath(os.path.join(exe_dir, "..", "Resources", relative_path)))
        candidates.append(os.path.abspath(os.path.join(exe_dir, relative_path)))
        # Directory containing RetestReport.app
        candidates.append(os.path.abspath(os.path.join(exe_dir, "..", "..", "..", relative_path)))

    # 3. Source directory (development mode)
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(proj_root, relative_path))
    candidates.append(os.path.abspath(relative_path))

    for c in candidates:
        if os.path.exists(c):
            return c

    return candidates[0] if candidates else os.path.abspath(relative_path)
