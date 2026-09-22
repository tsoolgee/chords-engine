"""בניית דף האקורדים: חלוקה לשורות, שיבוץ כל החלפת אקורד מעל האות הנכונה,
קטעים אינסטרומנטליים (פתיחה/מעבר/סיום) וחלוקה לבתים."""
from __future__ import annotations

import difflib

from .lyrics import normalize_word
from .theory import parse

LEAD = 0.35            # זמר/נגן מקדים: אקורד שמתחלף עד 0.35ש' לפני מילה שייך לה
TAIL = 0.30
INSTRUMENTAL_GAP = 4.0 # רווח בין שורות שממנו והלאה נוצר קטע אינסטרומנטלי
NC_MIN = 1.5           # "N.C." מוצג רק אם השקט ארוך מזה
MAX_LINE_CHARS = 48
MAX_LINE_WORDS = 9
SPLIT_GAP = 1.0


def _split_long(words: list[dict]) -> list[list[dict]]:
    """שורה ארוכה מדי נחתכת ברווח הגדול ביותר (מעדיף את האמצע)."""
    text_len = sum(len(w["text"]) + 1 for w in words)
    if len(words) <= 3 or (len(words) <= MAX_LINE_WORDS and text_len <= MAX_LINE_CHARS):
        return [words]
    best, best_score = None, -1.0
    n = len(words)
    for i in range(2, n - 1):
        gap = words[i]["start"] - words[i - 1]["end"]
        balance = 1 - abs(i - n / 2) / n
        score = gap + 0.3 * balance
        if score > best_score:
            best, best_score = i, score
    return _split_long(words[:best]) + _split_long(words[best:])


def build_lines(words: list[dict], known_lines: list[dict] | None = None) -> list[dict]:
    groups: list[tuple[list[dict], bool]] = []
    if known_lines:
        for kl in known_lines:
            ws = words[kl["start_word"]:kl["end_word"]]
            if ws:
                groups.append((ws, kl["stanza_break"]))
    else:
        cur: list[dict] = []
        for w in words:
            if cur and (w["segment"] != cur[-1]["segment"] or w["start"] - cur[-1]["end"] > SPLIT_GAP):
                groups.append((cur, False))
                cur = []
            cur.append(w)
        if cur:
            groups.append((cur, False))
        split = []
        for ws, br in groups:
            split.extend((part, br) for part in _split_long(ws))
        groups = split
        # מעבר בית = שתיקה של 3 שניות ומעלה
        for i in range(1, len(groups)):
            if groups[i][0][0]["start"] - groups[i - 1][0][-1]["end"] >= 3.0:
                groups[i] = (groups[i][0], True)
    lines = []
    for ws, br in groups:
        pos, lw = 0, []
        for w in ws:
            lw.append({"text": w["text"], "start": w["start"], "end": w["end"], "p": w.get("p", 1.0), "char": pos})
            pos += len(w["text"]) + 1
        lines.append({"type": "lyric", "start": ws[0]["start"], "end": ws[-1]["end"],
                      "text": " ".join(w["text"] for w in ws), "words": lw, "chords": [],
                      "stanza_break": br})
    return lines


def _char_for(line: dict, t: float) -> int:
    ws = line["words"]
    for k, w in enumerate(ws):
        if w["end"] > t:
            if t <= w["start"]:
                return w["char"]
            dur = w["end"] - w["start"]
            frac = (t - w["start"]) / max(0.05, dur)
            if dur >= 1.2 and len(w["text"]) > 2:
                # צליל ארוך (מלִיסמה): ההחלפה באמת באמצע המילה
                return w["char"] + min(len(w["text"]) - 1, round(frac * len(w["text"])))
            # זמני מילה של whisper גסים — נצמדים לתחילת המילה הקרובה
            if frac < 0.5 or k + 1 == len(ws):
                return w["char"]
            return ws[k + 1]["char"]
    return len(line["text"])            # אחרי המילה האחרונה


def attach_chords(lines: list[dict], chords: list[dict], duration: float, beats: list[float]) -> list[dict]:
    """מחזיר רשימת שורות מלאה: שורות מילים + קטעים אינסטרומנטליים, לפי סדר הזמן."""
    changes = []
    for c in chords:
        ch = parse(c["label"])
        if ch.is_none and c["end"] - c["start"] < NC_MIN:
            continue
        changes.append({"time": c["start"], "end": c["end"], "label": ch.to_harte()})

    def sounding(t: float) -> str | None:
        cur = None
        for c in changes:
            if c["time"] <= t + 1e-6:
                cur = c
            else:
                break
        return cur["label"] if cur and cur["end"] > t else None

    # חלון לכל שורה, בלי חפיפה
    for i, ln in enumerate(lines):
        ln["_w0"] = ln["start"] - LEAD
        nxt = lines[i + 1]["start"] - LEAD if i + 1 < len(lines) else float("inf")
        ln["_w1"] = min(ln["end"] + TAIL, nxt)

    out: list[dict] = []
    gap_chords: dict[int, list[dict]] = {}          # אינדקס השורה שאחרי הרווח -> אקורדים ברווח
    for c in changes:
        t = c["time"]
        placed = False
        for ln in lines:
            if ln["_w0"] <= t < ln["_w1"]:
                ln["chords"].append({"char": _char_for(ln, t), "label": c["label"], "time": round(t, 3), "carried": False})
                placed = True
                break
        if not placed:
            idx = next((i for i, ln in enumerate(lines) if ln["_w0"] > t), len(lines))
            gap_chords.setdefault(idx, []).append(c)

    # אורך פעמה ממוצע (חציון המרווחים) — לספירת תיבות בקטעים אינסטרומנטליים
    diffs = sorted(b - a for a, b in zip(beats, beats[1:]) if b > a)
    beat_len = diffs[len(diffs) // 2] if diffs else 0.5

    def beats_in(s: float, e: float) -> int:
        return max(1, round((e - s) / beat_len))

    for i in range(len(lines) + 1):
        prev_end = lines[i - 1]["_w1"] if i > 0 else 0.0
        next_start = lines[i]["_w0"] if i < len(lines) else duration
        gcs = gap_chords.get(i, [])
        long_gap = next_start - prev_end >= INSTRUMENTAL_GAP or i == 0 or i == len(lines)
        # רווח ארוך בלי החלפת אקורד (אקורד אחד מוחזק) עדיין מקבל קטע נגינה משלו
        held = i > 0 and not gcs and next_start - prev_end >= INSTRUMENTAL_GAP and sounding(prev_end)
        if (gcs or held) and long_gap:
            blk = []
            head = sounding(prev_end)
            if i > 0 and head and (not gcs or gcs[0]["time"] - prev_end > 0.5):
                blk.append({"label": head, "time": round(prev_end, 3), "carried": True})
            blk += [{"label": c["label"], "time": round(c["time"], 3), "carried": False} for c in gcs]
            blk = [b for b in blk if not parse(b["label"]).is_none]
            for j, b in enumerate(blk):
                end = blk[j + 1]["time"] if j + 1 < len(blk) else next_start
                b["duration"] = round(max(0.0, end - b["time"]), 3)
                b["beats"] = beats_in(b["time"], end)
            if blk:
                if not lines:
                    role = "instrumental"      # שיר בלי מילים / אקורדים בלבד
                else:
                    role = "intro" if i == 0 else ("outro" if i == len(lines) else "interlude")
                out.append({"type": "instrumental", "role": role, "start": round(max(0.0, prev_end), 3),
                            "end": round(next_start, 3), "chords": blk, "stanza_break": i > 0})
        elif gcs:
            # רווח קצר: כמה אקורדים מהירים -> כולם בסוף השורה הקודמת חוץ מהאחרון,
            # שפותח את השורה הבאה
            for c in gcs[:-1]:
                if i > 0:
                    ln = lines[i - 1]
                    ln["chords"].append({"char": len(ln["text"]), "label": c["label"], "time": round(c["time"], 3), "carried": False})
            c = gcs[-1]
            lines[i]["chords"].append({"char": 0, "label": c["label"], "time": round(c["time"], 3), "carried": False})
        if i < len(lines):
            out.append(lines[i])

    # אקורד שנפל בדיוק בסוף שורה (אחרי המילה האחרונה) עובר לפתוח את השורה הבאה
    for a, b in zip(lines, lines[1:]):
        if b["start"] - a["end"] >= INSTRUMENTAL_GAP:
            continue
        tail = [c for c in a["chords"] if c["char"] >= len(a["text"])]
        if len(tail) == 1:
            a["chords"].remove(tail[0])
            if not any(c["char"] == 0 and c["time"] > tail[0]["time"] for c in b["chords"]):
                b["chords"].append({**tail[0], "char": 0})

    for ln in lines:
        ln["chords"].sort(key=lambda c: (c["time"], c["char"]))
        # שני אקורדים על אותה אות: נשאר האחרון (הראשון היה קצר מדי לנגינה)
        dedup = []
        for c in ln["chords"]:
            if dedup and dedup[-1]["char"] == c["char"]:
                dedup[-1] = c
            else:
                dedup.append(c)
        ln["chords"] = dedup
        # אקורד שממשיך מהשורה הקודמת מוצג בתחילת השורה (carried)
        if not ln["chords"] or ln["chords"][0]["char"] > 0:
            s = sounding(ln["start"] - 0.05)
            if s and not parse(s).is_none:
                ln["chords"].insert(0, {"char": 0, "label": s, "time": round(ln["start"], 3), "carried": True})
        del ln["_w0"], ln["_w1"]
    return out


def mark_sections(lines: list[dict]) -> list[dict]:
    """מחלק לבתים לפי stanza_break ומסמן פזמון: הבית שהטקסט שלו חוזר הכי הרבה."""
    sections: list[list[int]] = []
    for i, ln in enumerate(lines):
        if ln["type"] == "instrumental":
            sections.append([i])
            continue
        if not sections or ln.get("stanza_break") or lines[sections[-1][-1]]["type"] == "instrumental":
            sections.append([])
        sections[-1].append(i)
    texts = []
    for sec in sections:
        t = " ".join(normalize_word(w) for i in sec for w in lines[i].get("text", "").split())
        texts.append(t)
    repeats = [0] * len(sections)
    for a in range(len(sections)):
        for b in range(len(sections)):
            if a != b and texts[a] and texts[b] and difflib.SequenceMatcher(None, texts[a], texts[b]).ratio() > 0.75:
                repeats[a] += 1
    top = max(repeats) if repeats else 0
    verse_n = chorus_n = 0
    result = []
    for si, sec in enumerate(sections):
        first = lines[sec[0]]
        if first["type"] == "instrumental":
            kind = first["role"]
        elif top > 0 and repeats[si] == top:
            kind = "chorus"
        else:
            kind = "verse"
        if kind == "chorus":
            chorus_n += 1
        elif kind == "verse":
            verse_n += 1
        sid = f"S{si + 1}"
        for i in sec:
            lines[i]["section"] = sid
        result.append({"id": sid, "kind": kind, "number": chorus_n if kind == "chorus" else verse_n,
                       "start": first["start"], "end": lines[sec[-1]]["end"]})
    for i, ln in enumerate(lines):
        ln["id"] = f"L{i + 1}"
    return result
