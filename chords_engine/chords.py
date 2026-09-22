"""זיהוי אקורדים (lv-chordia) וזיהוי קצב/פעמות (librosa)."""
from __future__ import annotations

import importlib.resources
from pathlib import Path

import numpy as np

from .jobs import CancelToken
from .theory import Chord, parse


def recognize(wav: Path, vocabulary: str = "submission", cancel: CancelToken | None = None,
              progress=None) -> list[dict]:
    """אותו אלגוריתם כמו lv_chordia.chord_recognition, עם התקדמות וביטול בין המודלים.
    מחזיר [{start, end, label}] עם תוויות Harte (C:maj, A:min7/b7, N)."""
    from lv_chordia.chord_recognition import MODEL_NAMES
    from lv_chordia.chordnet_ismir_naive import ChordNet
    from lv_chordia.extractors.cqt import CQTV2
    from lv_chordia.extractors.xhmm_ismir import XHMMDecoder
    from lv_chordia.mir import DataEntry, io
    from lv_chordia.mir.nn.train import NetworkInterface
    from lv_chordia.settings import DEFAULT_HOP_LENGTH, DEFAULT_SR

    with importlib.resources.path("lv_chordia.data", f"{vocabulary}_chord_list.txt") as f:
        hmm = XHMMDecoder(template_file=str(f))
    entry = DataEntry()
    entry.prop.set("sr", DEFAULT_SR)
    entry.prop.set("hop_length", DEFAULT_HOP_LENGTH)
    entry.append_file(str(Path(wav).resolve()), io.MusicIO, "music")
    entry.append_extractor(CQTV2, "cqt")
    cqt = entry.cqt                                     # החישוב הכבד הראשון
    steps = len(MODEL_NAMES) + 2
    if progress:
        progress(1 / steps)
    probs = []
    for i, name in enumerate(MODEL_NAMES):
        if cancel:
            cancel.check()
        net = NetworkInterface(ChordNet(None), name, load_checkpoint=False)
        probs.append(net.inference(cqt))
        if progress:
            progress((i + 2) / steps)
    probs = [np.mean([p[i] for p in probs], axis=0) for i in range(len(probs[0]))]
    lab = hmm.decode_to_chordlab(entry, probs, False)
    return [{"start": round(float(s), 3), "end": round(float(e), 3), "label": str(c)} for s, e, c in lab]


def beats(wav: Path) -> dict:
    """קצב (BPM) וזמני פעמות."""
    import librosa
    y, sr = librosa.load(str(wav), sr=22050, mono=True)
    tempo, frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    times = librosa.frames_to_time(frames, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    return {"tempo": round(tempo, 1), "beats": [round(float(t), 3) for t in times]}


def clean(segments: list[dict], beat_times: list[float] | None, min_dur: float,
          snap: bool = True) -> list[dict]:
    """ממזג אקורדים קצרים מדי, מאחד רצפים זהים ומיישר גבולות לפעמה הקרובה."""
    segs = [dict(s) for s in segments if s["end"] > s["start"]]
    # 1) אקורדים קצרים -> מתמזגים לשכן הארוך יותר
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for i, s in enumerate(segs):
            if s["end"] - s["start"] >= min_dur:
                continue
            prev = segs[i - 1] if i > 0 else None
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            tgt = prev if (nxt is None or (prev and prev["end"] - prev["start"] >= nxt["end"] - nxt["start"])) else nxt
            if tgt is prev:
                prev["end"] = s["end"]
            else:
                nxt["start"] = s["start"]
            segs.pop(i)
            changed = True
            break
    # 2) יישור לפעמות
    if snap and beat_times:
        bt = np.asarray(beat_times)
        for s in segs[1:]:
            j = int(np.argmin(np.abs(bt - s["start"])))
            if abs(bt[j] - s["start"]) <= 0.2:
                s["start"] = round(float(bt[j]), 3)
        for a, b in zip(segs, segs[1:]):
            a["end"] = b["start"]
        segs = [s for s in segs if s["end"] > s["start"]]
    # 3) איחוד רצפים זהים (אחרי נרמול: C:maj ו-C יתאחדו)
    out: list[dict] = []
    for s in segs:
        if out and parse(out[-1]["label"]) == parse(s["label"]):
            out[-1]["end"] = s["end"]
        else:
            out.append(s)
    return out


def timeline(segs: list[dict]) -> list[tuple[float, float, Chord]]:
    return [(s["start"], s["end"], parse(s["label"])) for s in segs]
