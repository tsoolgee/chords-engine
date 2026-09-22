"""קליטת עריכות מה-UI: תיקון מילים, הזזה/החלפה/מחיקה/הוספה של אקורדים, שינוי פרטי השיר."""
from __future__ import annotations

import copy

from .align import mark_sections
from .theory import parse

META_FIELDS = {"title", "artist", "album", "track", "year", "genre", "folder", "key", "tempo", "time_signature"}


def _relayout_words(line: dict, old: dict | None):
    """אחרי שינוי טקסט: מחשב מחדש מיקומי מילים ומנסה לשמור את הזמנים."""
    toks = line["text"].split()
    line["text"] = " ".join(toks)
    old_words = (old or {}).get("words") or line.get("words") or []
    start, end = line.get("start", 0.0), line.get("end", 0.0)
    words, pos = [], 0
    for i, t in enumerate(toks):
        if len(old_words) == len(toks):
            s, e, p = old_words[i]["start"], old_words[i]["end"], old_words[i].get("p", 1.0)
        else:
            step = (end - start) / max(1, len(toks))
            s, e, p = start + i * step, start + (i + 1) * step, 1.0
        words.append({"text": t, "start": s, "end": e, "p": p, "char": pos})
        pos += len(t) + 1
    line["words"] = words


def apply_edits(doc: dict, body: dict) -> dict:
    """body: {"meta": {...}, "lines": [...], "view": {"transpose": n, "capo": n}}.
    לכל אקורד: name (כפי שמוצג, בכל כתיב: Am7 / A:min7 / לה m7) — מפורש בסולם של view
    ומוחזר לסולם המקור; אם אין name, label נחשב כבר בסולם המקור."""
    doc = copy.deepcopy(doc)
    view = body.get("view") or {}
    back = -(int(view.get("transpose", 0)) - int(view.get("capo", 0)))

    for k, v in (body.get("meta") or {}).items():
        if k in META_FIELDS:
            doc["meta"][k] = v
    if "key" in (body.get("meta") or {}) and body["meta"]["key"]:
        from .theory import parse_key
        doc["meta"]["key"] = parse_key(body["meta"]["key"]).transpose(-int(view.get("transpose", 0))).name()

    if "lines" in body:
        old_by_id = {l.get("id"): l for l in doc["lines"]}
        new_lines = []
        for ln in body["lines"]:
            ln = copy.deepcopy(ln)
            typ = ln.get("type", "lyric")
            if typ not in ("lyric", "instrumental"):
                raise ValueError(f"סוג שורה לא מוכר: {typ}")
            old = old_by_id.get(ln.get("id"))
            ln.setdefault("start", old["start"] if old else 0.0)
            ln.setdefault("end", old["end"] if old else ln["start"])
            chords = []
            for c in ln.get("chords", []):
                # name = כפי שמוצג למשתמש (בסולם של view); label = בסולם המקור
                if c.get("name"):
                    ch = parse(c["name"]).transpose(back)   # ValueError -> 400 ב-API
                else:
                    ch = parse(c.get("label", ""))
                item = {"label": ch.to_harte(), "time": c.get("time", ln["start"]),
                        "carried": bool(c.get("carried", False))}
                if typ == "lyric":
                    item["char"] = max(0, int(c.get("char", 0)))
                else:
                    item["duration"] = c.get("duration", 0)
                    item["beats"] = c.get("beats", 0)
                chords.append(item)
            ln["chords"] = chords
            ln.pop("name", None)
            if typ == "lyric":
                ln["text"] = ln.get("text", "")
                if not old or old.get("text") != ln["text"] or "words" not in ln:
                    _relayout_words(ln, old)
                for c in ln["chords"]:
                    c["char"] = min(c["char"], len(ln["text"]))
                ln["chords"].sort(key=lambda c: (c["char"], c["time"]))
            else:
                ln.setdefault("role", "interlude")
            new_lines.append(ln)
        doc["lines"] = new_lines
        # ציר הזמן לנגן: אקורד שהוחלף בשורה מתעדכן גם בציר
        by_time = {round(c["time"], 2): c["label"] for l in new_lines for c in l["chords"] if not c.get("carried")}
        for t in doc["timeline"]:
            lab = by_time.get(round(t["start"], 2))
            if lab:
                t["label"] = lab
        if body.get("sections") is not None:
            doc["sections"] = body["sections"]
        else:
            doc["sections"] = mark_sections(doc["lines"])
    return doc
