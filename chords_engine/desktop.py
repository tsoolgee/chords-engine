"""נקודת הכניסה של התוכנה: מפעיל את המנוע ופותח חלון (WebView2 דרך pywebview).
אם pywebview לא זמין — פותח את Edge במצב אפליקציה, ונסגר כשהחלון נסגר."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__, config

TITLE = "אקורדים"
AUDIO_FILTER = ("קבצי שמע ווידאו (*.mp3;*.wav;*.flac;*.m4a;*.aac;*.ogg;*.opus;*.wma;*.mp4;*.mkv;*.webm;*.avi;*.mov)",
                "כל הקבצים (*.*)")


def _ours(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            return json.loads(r.read()).get("ok") is True
    except Exception:  # noqa: BLE001
        return False


def _free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _log_to_file():
    """ב-EXE בלי קונסול: הפלט נשמר לקובץ לוג (לאבחון תקלות)."""
    if sys.stdout is None or getattr(sys, "frozen", False):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        f = open(config.DATA_DIR / "engine.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
        print(f"\n=== {time.ctime()} v{__version__} ===")


class Api:
    """פונקציות שהממשק קורא דרך window.pywebview.api"""
    _window = None

    def pick_files(self):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        return list(self._window.create_file_dialog(kind, allow_multiple=True, file_types=AUDIO_FILTER) or [])

    def pick_folder(self):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        res = self._window.create_file_dialog(kind)
        return list(res or [])

    def save_file(self, name: str, content: str):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        res = self._window.create_file_dialog(kind, save_filename=name)
        if not res:
            return None
        path = res if isinstance(res, str) else res[0]
        Path(path).write_text(content, encoding="utf-8-sig")
        return path

    def open_folder(self, path: str):
        subprocess.Popen(["explorer", "/select,", path])

    def fullscreen(self):
        self._window.toggle_fullscreen()

    def keep_awake(self, on: bool):
        # ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED — מצב הופעה: המסך לא נכבה
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x3 if on else 0))


def _edge_app(url: str) -> bool:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        exe = Path(base or "") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if exe.exists():
            prof = config.DATA_DIR / "edge"
            proc = subprocess.Popen([str(exe), f"--app={url}", f"--user-data-dir={prof}", "--no-first-run"])
            proc.wait()
            return True
    import webbrowser
    webbrowser.open(url)
    return False


def main():
    _log_to_file()
    port = config.DEFAULT_PORT
    if _ours(port):                      # התוכנה כבר פתוחה — חלון נוסף לאותו מנוע
        _edge_app(f"http://127.0.0.1:{port}/")
        return
    while not _free(port):
        port += 1
    from .server import serve
    threading.Thread(target=serve, args=("127.0.0.1", port), daemon=True).start()
    for _ in range(100):
        if _ours(port):
            break
        time.sleep(0.1)
    url = f"http://127.0.0.1:{port}/ui/index.html"
    try:
        import webview
        api = Api()
        api._window = webview.create_window(TITLE, url, js_api=api, width=1360, height=880,
                                           min_size=(900, 600), text_select=True)

        def on_drop(e):
            files = (e.get("dataTransfer") or {}).get("files") or []
            paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if paths:
                api._window.evaluate_js(f"window.onNativeDrop({json.dumps(paths)})")

        def on_loaded():
            try:     # גרירת קבצים עם נתיב מלא (בלי העתקה)
                from webview.dom import DOMEventHandler
                api._window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
                api._window.evaluate_js("window.__nativeDrop = true")
            except Exception as ex:  # noqa: BLE001
                print("drop handler:", ex)

        api._window.events.loaded += on_loaded
        webview.start(gui="edgechromium", private_mode=False,
                      storage_path=str(config.DATA_DIR / "webview"))
    except Exception as e:  # noqa: BLE001
        print("pywebview נכשל, עובר ל-Edge:", e)
        from .server import LAST_PING
        opened = _edge_app(url)
        if not opened:                   # דפדפן רגיל: נשארים חיים כל עוד הדף שולח ping
            while time.time() - LAST_PING[0] < 60:
                time.sleep(5)
    os._exit(0)


if __name__ == "__main__":
    main()
