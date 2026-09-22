"""הפיכת מסמך השיר (בסולם המקורי) לתצוגה: טרנספוזיציה, קאפו, פישוט, כתיב,
וייצוא ל-ChordPro / טקסט / LRC."""
from __future__ import annotations

import copy

from . import theory
from .theory import Key, format_chord, parse, simplify

RLM = chr(0x200F)  # סימן כיוון ימין-לשמאל

DEFAULT_VIEW = {
    "transpose": 0,          # חצאי טונים (-11..11) — משנה את הצליל
    "capo": 0,               # קאפו (0..11) — משנה רק את האצבוע המוצג
    "simplify": "standard",  # basic | standard | full
    "notation": "letters",   # letters | solfege_he | solfege
    "accidentals": "auto",   # auto | sharps | flats
    "show_carried": True,    # להציג את האקורד שממשיך בתחילת כל שורה
    "include_shapes": True,  # אצבועי גיטרה ופסנתר לכל אקורד בשיר
}


def view_options(q: dict) -> dict:
    o = dict(DEFAULT_VIEW)
    for k, v in (q or {}).items():
        if k not in o:
            continue
        if isinstance(o[k], bool):
            o[k] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
        elif isinstance(o[k], int):
            o[k] = int(v)
        else:
            o[k] = str(v)
    o["transpose"] = ((o["transpose"] + 6) % 12) - 6     # -6..5
    o["capo"] = o["capo"] % 12
    return o


def render(doc: dict, opts: dict | None = None) -> dict:
    o = view_options(opts or {})
    shift = o["transpose"] - o["capo"]
    orig_key = theory.parse_key(doc["meta"]["key"]) if doc["meta"].get("key") else None
    sounding_key = orig_key.transpose(o["transpose"]) if orig_key else None
    shape_key = orig_key.transpose(shift) if orig_key else None
    flats = theory.flat_policy(shape_key, o["accidentals"])

    def name(label: str) -> str:
        return format_chord(simplify(parse(label), o["simplify"]).transpose(shift), o["notation"], flats)

    out = copy.deepcopy(doc)
    used: dict[str, str] = {}
    for ln in out["lines"]:
        chords = ln["chords"]
        if not o["show_carried"]:
            chords = [c for c in chords if not c.get("carried")]
        for c in chords:
            c["name"] = name(c["label"])
            if not parse(c["label"]).is_none:
                used.setdefault(c["name"], c["label"])
        ln["chords"] = chords
    out["timeline"] = [{**t, "name": name(t["label"])} for t in doc["timeline"]]

    chords_used = []
    for nm, label in used.items():
        ch = simplify(parse(label), o["simplify"]).transpose(shift)
        item = {"name": nm, "label": ch.to_harte()}
        if o["include_shapes"]:
            item["guitar"] = theory.guitar_shapes(ch)
            item["piano"] = theory.piano_notes(ch)
        chords_used.append(item)
    out["chords_used"] = chords_used

    tl = [(t["start"], t["end"], simplify(parse(t["label"]), o["simplify"]).transpose(o["transpose"]))
          for t in doc["timeline"]]
    out["capo_suggestions"] = theory.suggest_capo(tl)[:3]
    m = out["meta"]
    key_flats = None if o["accidentals"] == "auto" else o["accidentals"] == "flats"
    m["key_original"] = orig_key.name(o["notation"], key_flats) if orig_key else None
    m["key"] = sounding_key.name(o["notation"], key_flats) if sounding_key else None
    m["shape_key"] = shape_key.name(o["notation"], key_flats) if shape_key else None
    out["view"] = o
    return out


# ---------------------------------------------------------------- ייצוא

def _chord_line(ln: dict) -> tuple[str, str]:
    """שורת אקורדים מעל שורת מילים, מונוספייס. RLM אחרי כל אקורד שומר על
    כיווניות ימין-לשמאל גם כשיש רק אותיות לטיניות בשורה."""
    text = ln["text"]
    cells: list[str] = []
    pos = 0
    for c in ln["chords"]:
        at = max(c["char"], pos)
        cells.append(" " * (at - pos) + c["name"] + RLM)
        pos = at + len(c["name"]) + 1
        cells.append(" ")
    chord_line = "".join(cells).rstrip()
    return RLM + chord_line, RLM + text


def _section_title(sec: dict) -> str:
    names = {"verse": "בית", "chorus": "פזמון", "intro": "פתיחה", "interlude": "מעבר",
             "outro": "סיום", "instrumental": "נגינה"}
    n = names.get(sec["kind"], sec["kind"])
    return f"{n} {sec['number']}" if sec["kind"] in ("verse", "chorus") and sec.get("number") else n


def to_text(view: dict) -> str:
    m = view["meta"]
    head = [m.get("title") or "", m.get("artist") or ""]
    info = [f"סולם: {m['key']}" if m.get("key") else "", f"קצב: {round(m['tempo'])}" if m.get("tempo") else ""]
    if view["view"]["capo"]:
        info.append(f"קאפו: {view['view']['capo']} (אצבוע בסולם {m['shape_key']})")
    lines = [RLM + h for h in head if h] + [RLM + "  |  ".join(i for i in info if i), ""]
    secs = {s["id"]: s for s in view.get("sections", [])}
    cur = None
    for ln in view["lines"]:
        if ln.get("section") != cur:
            cur = ln.get("section")
            if cur in secs:
                if lines and lines[-1] != "":
                    lines.append("")
                lines.append(RLM + f"[{_section_title(secs[cur])}]")
        if ln["type"] == "instrumental":
            # כל תיבה (4 פעמות) מקבלת תא: | C | C | G | Am |
            cells = []
            for c in ln["chords"]:
                bars = max(1, round(c.get("beats", 4) / 4))
                cells += [c["name"] + RLM] * min(bars, 8)
            lines.append(RLM + "| " + " | ".join(cells) + " |")
        else:
            a, b = _chord_line(ln)
            if ln["chords"]:
                lines.append(a)
            lines.append(b)
    return "\n".join(lines).rstrip() + "\n"


def to_chordpro(view: dict) -> str:
    m = view["meta"]
    out = []
    if m.get("title"):
        out.append(f"{{title: {m['title']}}}")
    if m.get("artist"):
        out.append(f"{{artist: {m['artist']}}}")
    if m.get("key"):
        out.append(f"{{key: {m['key']}}}")
    if m.get("tempo"):
        out.append(f"{{tempo: {round(m['tempo'])}}}")
    if view["view"]["capo"]:
        out.append(f"{{capo: {view['view']['capo']}}}")
    out.append("")
    secs = {s["id"]: s for s in view.get("sections", [])}
    cur = None
    open_env = None
    for ln in view["lines"]:
        if ln.get("section") != cur:
            if open_env:
                out.append(f"{{end_of_{open_env}}}")
                open_env = None
            cur = ln.get("section")
            sec = secs.get(cur)
            if sec:
                out.append("")
                if sec["kind"] in ("verse", "chorus"):
                    open_env = sec["kind"]
                    out.append(f"{{start_of_{open_env}: {_section_title(sec)}}}")
                else:
                    out.append(f"{{comment: {_section_title(sec)}}}")
        if ln["type"] == "instrumental":
            out.append(" ".join(f"[{c['name']}]" for c in ln["chords"]))
            continue
        text = ln["text"]
        s = ""
        pos = 0
        for c in sorted(ln["chords"], key=lambda c: c["char"]):
            at = min(c["char"], len(text))
            s += text[pos:at] + f"[{c['name']}]"
            pos = at
        out.append(s + text[pos:])
    if open_env:
        out.append(f"{{end_of_{open_env}}}")
    return "\n".join(out).strip() + "\n"


def to_lrc(view: dict) -> str:
    out = []
    m = view["meta"]
    if m.get("title"):
        out.append(f"[ti:{m['title']}]")
    if m.get("artist"):
        out.append(f"[ar:{m['artist']}]")
    for ln in view["lines"]:
        t = ln["start"]
        stamp = f"[{int(t // 60):02d}:{t % 60:05.2f}]"
        if ln["type"] == "instrumental":
            out.append(stamp + " " + " ".join(c["name"] for c in ln["chords"]))
        else:
            out.append(stamp + ln["text"])
    return "\n".join(out) + "\n"


EXPORTERS = {
    "txt": (to_text, "text/plain; charset=utf-8", ".txt"),
    "chordpro": (to_chordpro, "text/plain; charset=utf-8", ".cho"),
    "lrc": (to_lrc, "text/plain; charset=utf-8", ".lrc"),
}
