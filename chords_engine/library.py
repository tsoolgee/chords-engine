"""ספריית שירים על הדיסק. לכל שיר תיקייה <id> עם:
  analysis.json  — תוצאת הניתוח (קיים רק אחרי ניתוח שהושלם; משמש ל"חזרה לזיהוי המקורי")
  song.json      — המסמך הנוכחי, כולל עריכות המשתמש (נכתב גם תוך כדי ניתוח)
  cover.jpg      — תמונת אלבום (אם יש)
  play.wav       — עותק לניגון לפורמטים שהממשק לא מנגן (mkv, avi, wma)
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

from . import config

_lock = threading.Lock()


def song_dir(song_id: str) -> Path:
    if not song_id or not all(c in "0123456789abcdef" for c in song_id):
        raise KeyError(song_id)
    return config.LIBRARY_DIR / song_id


def _write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def save_analysis(doc: dict):
    d = song_dir(doc["id"])
    _write(d / "analysis.json", doc)
    _write(d / "song.json", doc)


def load(song_id: str) -> dict:
    p = song_dir(song_id) / "song.json"
    if not p.exists():
        raise KeyError(song_id)
    with _lock:
        return json.loads(p.read_text(encoding="utf-8"))


def save(doc: dict, touch: bool = True):
    if touch:
        doc["modified"] = time.time()
    _write(song_dir(doc["id"]) / "song.json", doc)


def reset(song_id: str) -> dict:
    d = song_dir(song_id)
    if not (d / "analysis.json").exists():
        raise KeyError(song_id)
    shutil.copyfile(d / "analysis.json", d / "song.json")
    return load(song_id)


def exists(song_id: str) -> bool:
    return (song_dir(song_id) / "song.json").exists()


def is_complete(song_id: str) -> bool:
    return (song_dir(song_id) / "analysis.json").exists()


def delete(song_id: str):
    shutil.rmtree(song_dir(song_id), ignore_errors=True)


def summary(doc: dict) -> dict:
    m = doc["meta"]
    return {"id": doc["id"], "title": m.get("title"), "artist": m.get("artist", ""), "album": m.get("album", ""),
            "track": m.get("track", ""), "year": m.get("year", ""), "genre": m.get("genre", ""),
            "folder": m.get("folder", ""), "has_cover": m.get("has_cover", False),
            "key": m.get("key"), "tempo": m.get("tempo"), "duration": m.get("duration"),
            "source_path": doc["source"]["path"], "is_video": doc["source"].get("is_video", False),
            "created": doc.get("created"), "modified": doc.get("modified"),
            "state": doc.get("analysis_state", "done"),
            "has_lyrics": any(l["type"] == "lyric" for l in doc["lines"])}


def list_songs() -> list[dict]:
    out = []
    if not config.LIBRARY_DIR.exists():
        return out
    for d in config.LIBRARY_DIR.iterdir():
        p = d / "song.json"
        if not p.exists():
            continue
        try:
            out.append(summary(json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError):
            continue
    out.sort(key=lambda s: -(s["modified"] or s["created"] or 0))
    return out
