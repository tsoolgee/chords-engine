"""נתיבים והגדרות ברירת מחדל. אפשר לדרוס כל נתיב במשתנה סביבה."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _root() -> Path:
    # בתוך EXE של PyInstaller התיקייה vendor יושבת ליד קובץ ה-EXE
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


ROOT = _root()
VENDOR = Path(os.environ.get("CHORDS_VENDOR", ROOT / "vendor"))
WHISPER_CLI = Path(os.environ.get("CHORDS_WHISPER_CLI", VENDOR / "whisper" / "Release" / "whisper-cli.exe"))
DATA_DIR = Path(os.environ.get("CHORDS_DATA", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ChordsEngine"))
LIBRARY_DIR = DATA_DIR / "library"
# מודלים: ליד התוכנה (vendor/models) או בתיקיית הנתונים של המשתמש
MODELS_DIR = Path(os.environ.get("CHORDS_MODELS", VENDOR / "models"))
MODEL_DIRS = [MODELS_DIR, DATA_DIR / "models"]
UI_DIR = Path(__file__).resolve().parent / "ui"

DEFAULT_WHISPER_MODEL = "ggml-ivrit-large-v3-turbo-q5_0.bin"
DEFAULT_PORT = 8765

# ברירות המחדל של ניתוח (ה-UI יכול לשנות כל אחת)
DEFAULT_ANALYZE_OPTIONS = {
    "language": "he",            # שפת השירה
    "whisper_model": DEFAULT_WHISPER_MODEL,
    "accurate_timing": False,    # DTW: תזמון מילים מדויק יותר, בערך +40% זמן
    "threads": max(1, os.cpu_count() or 4),
    "vad": False,                # ניסיוני: מהיר פי 2, אבל בבדיקות איבד שורה ראשונה והזיז זמני מילים
    "separate_vocals": False,    # הפרדת שירה (demucs, אם מותקן) לפני התמלול
    "chord_vocabulary": "submission",   # submission (~170 אקורדים) | ismir2017 (מז'ור/מינור) | full
    "min_chord_duration": 0.35,  # אקורדים קצרים מזה מתמזגים לשכן
    "snap_to_beats": True,
    "prompt": "",                # רמז לוויספר: שם השיר, מילים נדירות
    "lyrics_text": "",           # מילים ידועות: אם הודבקו, הן מיושרות לאודיו במקום התמלול
    "skip_lyrics": False,        # אקורדים בלבד (מהיר)
    "folder": "",                # תיקייה בספרייה ("הופעות/2026")
}


def _model_files(pattern: str) -> list[Path]:
    out = []
    for d in MODEL_DIRS:
        if d.exists():
            out += [p for p in d.glob(pattern) if p.stat().st_size > 100_000]   # דף חסימה של נטפרי < 2KB
    return out


def whisper_model_path(name: str) -> Path:
    p = Path(name)
    if p.is_absolute():
        return p
    for d in MODEL_DIRS:
        if (d / name).exists():
            return d / name
    # המודל המבוקש לא קיים — כל מודל עברית אחר שנמצא עדיף על כישלון
    others = [m for m in _model_files("ggml-*.bin") if "silero" not in m.name]
    return others[0] if others else MODELS_DIR / name


def available_models() -> list[str]:
    return sorted({p.name for p in _model_files("ggml-*.bin") if "silero" not in p.name})


def vad_model_path() -> Path | None:
    hits = sorted(_model_files("ggml-silero*.bin"))
    return hits[-1] if hits else None
