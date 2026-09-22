"""תמלול מילים עם whisper.cpp (whisper-cli.exe) וחותמות זמן לכל מילה,
ויישור מילים ידועות (שהמשתמש הדביק) לזמנים של התמלול."""
from __future__ import annotations

import difflib
import json
import re
import tempfile
from pathlib import Path

from . import config
from .audio import run
from .jobs import CancelToken

_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")
_JUNK_RE = re.compile(r"^[\s\W]*$|^\s*[\[(（].*[\])）]\s*$|♪")
_NIQQUD_RE = re.compile("[" + chr(0x591) + "-" + chr(0x5C7) + "]")  # טעמים וניקוד
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def transcribe(wav16k: Path, opts: dict, cancel: CancelToken | None = None, progress=None, on_line=None) -> dict:
    """מריץ whisper-cli ומחזיר {'segments': [...], 'words': [...]}."""
    model = config.whisper_model_path(opts["whisper_model"])
    if not model.exists():
        raise FileNotFoundError(f"מודל whisper לא נמצא: {model}")
    if not config.WHISPER_CLI.exists():
        raise FileNotFoundError(f"whisper-cli.exe לא נמצא: {config.WHISPER_CLI}")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "w"
        cmd = [str(config.WHISPER_CLI), "-m", str(model), "-f", str(wav16k),
               "-l", opts.get("language") or "he", "-t", str(opts.get("threads", 4)),
               "-bs", "1", "-bo", "1", "-ojf", "-of", str(out), "-pp"]
        if opts.get("accurate_timing"):
            cmd += ["-nfa", "-dtw", "large.v3.turbo" if "turbo" in model.name else "large.v3"]
        vad = config.vad_model_path()
        if opts.get("vad") is True and vad:
            cmd += ["--vad", "-vm", str(vad)]
        if opts.get("prompt"):
            cmd += ["--prompt", opts["prompt"]]

        def handle(s):
            m = _PROGRESS_RE.search(s)
            if m and progress:
                progress(int(m.group(1)) / 100)
            elif on_line:
                on_line(s)             # שורות תמלול שהודפסו — לניתוח החי

        run(cmd, cancel, handle)
        raw = (out.with_suffix(".json")).read_bytes()
    # טוקנים של עברית יכולים לחתוך תו UTF-8 באמצע — surrogateescape שומר את הבתים
    data = json.loads(raw.decode("utf-8", "surrogateescape"))
    return parse_whisper_json(data)


def _fix(s: str) -> str:
    return s.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def parse_whisper_json(data: dict) -> dict:
    segments, words = [], []
    for seg in data.get("transcription", []):
        text = _fix(seg.get("text", "")).strip()
        if not text or _JUNK_RE.search(text):
            continue
        seg_start = seg["offsets"]["from"] / 1000
        seg_end = seg["offsets"]["to"] / 1000
        cur = None
        seg_words = []
        for tok in seg.get("tokens", []):
            t = tok.get("text", "")
            if t.startswith("[_") or t.startswith("<|"):
                continue
            t0 = tok["offsets"]["from"] / 1000
            t1 = max(t0, tok["offsets"]["to"] / 1000)
            if tok.get("t_dtw", -1) not in (-1, None):
                t0 = tok["t_dtw"] / 100
            if cur is None or t.startswith(" "):
                cur = {"raw": t.lstrip(" "), "start": t0, "end": t1, "p": [tok.get("p", 1.0)]}
                seg_words.append(cur)
            else:
                cur["raw"] += t
                cur["end"] = max(cur["end"], t1)
                cur["p"].append(tok.get("p", 1.0))
        clean_words = []
        for w in seg_words:
            txt = _fix(w["raw"]).strip()
            if not txt:
                continue
            if not re.search(r"\w", txt) and clean_words:
                clean_words[-1]["text"] += txt          # פיסוק נצמד למילה הקודמת
                continue
            clean_words.append({"text": txt, "start": round(w["start"], 3), "end": round(w["end"], 3),
                                "p": round(min(w["p"]), 3)})
        # עם DTW: סוף מילה = תחילת המילה הבאה (הזמנים של DTW הם נקודות התחלה)
        for a, b in zip(clean_words, clean_words[1:]):
            if a["end"] > b["start"] or a["end"] <= a["start"]:
                a["end"] = max(a["start"] + 0.05, b["start"])
        if not clean_words:
            continue
        seg_idx = len(segments)
        for w in clean_words:
            w["segment"] = seg_idx
        words.extend(clean_words)
        segments.append({"start": round(seg_start, 3), "end": round(seg_end, 3), "text": text})
    return {"segments": segments, "words": words}


# ------------------------------------------------------------ מילים ידועות

def normalize_word(w: str) -> str:
    w = _NIQQUD_RE.sub("", w)
    w = re.sub(r"[^\w]", "", w)
    return w.translate(_FINALS).lower()


def align_known_lyrics(recognized: list[dict], text: str) -> dict:
    """מיישר מילים שהמשתמש הדביק לזמני המילים שזוהו.
    שורות = שורות הטקסט; שורה ריקה = מעבר בית (stanza).
    מחזיר {'words': [...], 'lines': [{'start_word', 'end_word', 'stanza_break'}]}."""
    lines_words: list[list[str]] = []
    stanza_flags: list[bool] = []
    pending_break = False
    for ln in text.replace("\r", "").split("\n"):
        toks = ln.split()
        if not toks:
            pending_break = bool(lines_words)
            continue
        lines_words.append(toks)
        stanza_flags.append(pending_break)
        pending_break = False
    known = [w for ln in lines_words for w in ln]
    if not known:
        return {"words": [], "lines": []}
    kn = [normalize_word(w) for w in known]
    rn = [normalize_word(w["text"]) for w in recognized]
    times: list[tuple[float, float, float] | None] = [None] * len(known)
    sm = difflib.SequenceMatcher(None, rn, kn, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                r = recognized[i1 + k]
                times[j1 + k] = (r["start"], r["end"], r.get("p", 1.0))
        elif op == "replace":
            span_s, span_e = recognized[i1]["start"], recognized[i2 - 1]["end"]
            lens = [max(1, len(kn[j])) for j in range(j1, j2)]
            tot = sum(lens)
            t = span_s
            for j, L in zip(range(j1, j2), lens):
                d = (span_e - span_s) * L / tot
                times[j] = (t, t + d, 0.5)
                t += d
    # מילים שלא נמצאו בכלל: אינטרפולציה בין השכנים
    n = len(times)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else (times[j][0] - 0.4 * (j - i) if j < n else 0.0)
        right = times[j][0] if j < n else left + 0.4 * (j - i)
        left = max(0.0, left)
        step = max(0.05, (right - left) / (j - i))
        for k in range(i, j):
            s = left + step * (k - i)
            times[k] = (s, s + step, 0.0)
        i = j
    words = []
    lines = []
    idx = 0
    for li, ln in enumerate(lines_words):
        first = idx
        for w in ln:
            s, e, p = times[idx]
            words.append({"text": w, "start": round(s, 3), "end": round(max(e, s + 0.05), 3),
                          "p": round(p, 3), "segment": li})
            idx += 1
        lines.append({"start_word": first, "end_word": idx, "stanza_break": stanza_flags[li]})
    return {"words": words, "lines": lines}
