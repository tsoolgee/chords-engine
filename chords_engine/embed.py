"""ייצוא קובץ השמע המקורי עם המילים והאקורדים מוטמעים בתוכו.

השמע לא נוגע — רק נוספות תגיות, כך שכל נגן ינגן את אותו קובץ:
  MP3 (ID3v2)      SYLT (מילים מסונכרנות, content-type 1) + SYLT (אקורדים, content-type 5)
                   USLT (מילים כטקסט) + TXXX:CHORDS / TXXX:CHORDS_JSON / TXXX:CHORDPRO
  MP4 / M4A        ©lyr (LRC של המילים) + אטומים חופשיים com.chords.* לאקורדים ול-JSON
  FLAC / OGG / OPUS  תגיות LYRICS, CHORDS, CHORDS_JSON, CHORDPRO

ה-JSON הוא אותו מבנה של /api/songs/{id} (שורות, אקורדים, זמנים) — נגן שיודע לקרוא
אותו מקבל הכול; נגן רגיל יציג לפחות את המילים המסונכרנות.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import render

APP = "ChordsEngine"
MEDIA_EXT = {".mp3", ".mp4", ".m4a", ".m4v", ".flac", ".ogg", ".oga", ".opus"}


def _lrc_pairs(view: dict, what: str) -> list[tuple[int, str]]:
    """[(מילישניות, טקסט)] — 'lyrics' לשורות המילים, 'chords' לשמות האקורדים."""
    out: list[tuple[int, str]] = []
    if what == "chords":
        for t in view["timeline"]:
            if t["name"] != "N.C.":
                out.append((int(t["start"] * 1000), t["name"]))
    else:
        for ln in view["lines"]:
            if ln["type"] == "lyric" and ln.get("text"):
                out.append((int(ln["start"] * 1000), ln["text"]))
            elif ln["type"] == "instrumental" and ln["chords"]:
                out.append((int(ln["start"] * 1000), "♪ " + " ".join(c["name"] for c in ln["chords"])))
    out.sort()
    return out


def _lrc_text(pairs: list[tuple[int, str]]) -> str:
    return "\n".join(f"[{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}]{txt}" for ms, txt in pairs)


def payload(view: dict) -> dict:
    """מה שנשמר בתוך הקובץ, בכל הפורמטים."""
    return {
        "lyrics_lrc": _lrc_text(_lrc_pairs(view, "lyrics")),
        "chords_lrc": _lrc_text(_lrc_pairs(view, "chords")),
        "chordpro": render.to_chordpro(view),
        "text": render.to_text(view),
        "json": json.dumps({
            "app": APP, "version": view.get("engine_version"), "meta": view["meta"],
            "sections": view.get("sections", []), "lines": view["lines"],
            "timeline": view["timeline"], "beats": view.get("beats", []),
            "chords_used": [c["name"] for c in view.get("chords_used", [])],
        }, ensure_ascii=False),
    }


def _write_mp3(dst: Path, view: dict, p: dict):
    from mutagen.id3 import ID3, SYLT, TXXX, USLT
    from mutagen.mp3 import MP3
    f = MP3(dst)
    if f.tags is None:
        f.add_tags()
    tags: ID3 = f.tags
    for key in list(tags.keys()):
        if key.startswith(("SYLT", "USLT")) or key.startswith("TXXX:CHORD"):
            del tags[key]
    lang, m = "heb", view["meta"]
    # ערוץ המילים (content type 1) וערוץ האקורדים (content type 5 = Chord בתקן ID3)
    tags.add(SYLT(encoding=1, lang=lang, format=2, type=1, desc="lyrics",
                  text=[(t, ms) for ms, t in _lrc_pairs(view, "lyrics")]))
    tags.add(SYLT(encoding=1, lang=lang, format=2, type=5, desc="chords",
                  text=[(t, ms) for ms, t in _lrc_pairs(view, "chords")]))
    tags.add(USLT(encoding=1, lang=lang, desc="", text=p["text"]))
    tags.add(TXXX(encoding=1, desc="CHORDS", text=p["chords_lrc"]))
    tags.add(TXXX(encoding=1, desc="CHORDPRO", text=p["chordpro"]))
    tags.add(TXXX(encoding=1, desc="CHORDS_JSON", text=p["json"]))
    tags.add(TXXX(encoding=1, desc="KEY", text=m.get("key") or ""))
    tags.add(TXXX(encoding=1, desc="BPM", text=str(m.get("tempo") or "")))
    f.save(v2_version=4)


def _write_mp4(dst: Path, view: dict, p: dict):
    from mutagen.mp4 import MP4, MP4FreeForm
    f = MP4(dst)

    def ff(name, value):
        f.tags[f"----:com.{APP.lower()}:{name}"] = [MP4FreeForm(value.encode("utf-8"))]

    if f.tags is None:
        f.add_tags()
    f.tags["\xa9lyr"] = [p["lyrics_lrc"] or p["text"]]
    ff("CHORDS", p["chords_lrc"])
    ff("CHORDPRO", p["chordpro"])
    ff("CHORDS_JSON", p["json"])
    ff("KEY", view["meta"].get("key") or "")
    f.save()


def _write_vorbis(dst: Path, view: dict, p: dict):
    import mutagen
    f = mutagen.File(dst)
    if f is None:
        raise ValueError("פורמט לא נתמך")
    if f.tags is None:
        f.add_tags()
    f["LYRICS"] = p["lyrics_lrc"] or p["text"]
    f["CHORDS"] = p["chords_lrc"]
    f["CHORDPRO"] = p["chordpro"]
    f["CHORDS_JSON"] = p["json"]
    f["KEY"] = view["meta"].get("key") or ""
    f.save()


def export_media(view: dict, src: Path, dst: Path) -> Path:
    """מעתיק את קובץ המקור ל-dst ומטמיע בו את המילים והאקורדים."""
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"קובץ המקור לא נמצא: {src}")
    ext = src.suffix.lower()
    if ext not in MEDIA_EXT:
        raise ValueError(f"אי אפשר להטמיע בפורמט {ext} — אפשר לייצא ל-LRC או ChordPro במקום")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    p = payload(view)
    if ext == ".mp3":
        _write_mp3(dst, view, p)
    elif ext in (".mp4", ".m4a", ".m4v"):
        _write_mp4(dst, view, p)
    else:
        _write_vorbis(dst, view, p)
    return dst


def read_embedded(path: Path) -> dict:
    """קריאה חזרה — לבדיקה, ולמי שיכתוב נגן משלו."""
    import mutagen
    f = mutagen.File(path)
    out: dict = {"format": type(f).__name__, "lyrics": None, "chords": None, "json": None}
    tags = f.tags
    if tags is None:
        return out
    if hasattr(tags, "getall"):                      # ID3
        for s in tags.getall("SYLT"):
            out["chords" if s.type == 5 else "lyrics"] = [(ms, t) for t, ms in s.text]
        for t in tags.getall("TXXX"):
            if t.desc == "CHORDS_JSON":
                out["json"] = json.loads(t.text[0])
    else:
        get = (lambda k: tags.get(k, [None])[0]) if not hasattr(tags, "get") else (lambda k: (tags.get(k) or [None])[0])
        raw = get("\xa9lyr") or get("LYRICS")
        out["lyrics"] = raw if isinstance(raw, str) else (raw.decode("utf-8") if raw else None)
        for key in (f"----:com.{APP.lower()}:CHORDS", "CHORDS"):
            v = get(key)
            if v:
                out["chords"] = v if isinstance(v, str) else bytes(v).decode("utf-8")
                break
        for key in (f"----:com.{APP.lower()}:CHORDS_JSON", "CHORDS_JSON"):
            v = get(key)
            if v:
                out["json"] = json.loads(v if isinstance(v, str) else bytes(v).decode("utf-8"))
                break
    return out
