"""צינור הניתוח: קובץ שמע/וידאו -> מסמך שיר. התוצאות נשמרות בהדרגה (ניתוח חי):
  media  — Metadata, תמונה, צורת גל: הנגן מוכן תוך שניות
  chords — ציר אקורדים, סולם, קצב: אפשר לנגן עם אקורד נוכחי/הבא
  lyrics — שורות מילים מתווספות תוך כדי התמלול
  done   — מילים עם זמן לכל מילה, שיבוץ סופי, בתים
"""
from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

from . import __version__, align, audio, chords, config, library, lyrics, theory
from .jobs import Job

DOC_VERSION = 2
BROWSER_PLAYABLE = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".mp4", ".m4v", ".webm"}
_SEG_RE = re.compile(r"^\[(\d+):(\d+):(\d+(?:\.\d+)?) --> (\d+):(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$")


def plan(job: Job):
    """קובע מראש אילו שלבים ידולגו, כדי שה-UI יציג את רשימת השלבים הנכונה."""
    opts = {**config.DEFAULT_ANALYZE_OPTIONS, **(job.options or {})}
    if opts["skip_lyrics"]:
        job.skipped |= {"vocals", "lyrics"}
    if not opts["separate_vocals"] or not audio.demucs_available():
        job.skipped.add("vocals")


def song_id_for(path: Path) -> str:
    return audio.file_hash(path)[:16]


def _secs(h, m, s) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def _rough_words(segments: list[dict]) -> list[dict]:
    """מילים משוערות מתוך שורות שכבר הודפסו (לפני שיש זמן לכל מילה): הזמן מתחלק לפי אורך."""
    words = []
    for si, seg in enumerate(segments):
        toks = seg["text"].split()
        total = sum(len(t) + 1 for t in toks) or 1
        t = seg["start"]
        for tok in toks:
            d = (seg["end"] - seg["start"]) * (len(tok) + 1) / total
            words.append({"text": tok, "start": round(t, 3), "end": round(t + d, 3), "p": 1.0, "segment": si})
            t += d
    return words


def analyze(job: Job) -> str:
    opts = {**config.DEFAULT_ANALYZE_OPTIONS, **(job.options or {})}
    src = Path(job.path)
    if not src.exists():
        raise FileNotFoundError(f"הקובץ לא נמצא: {src}")
    plan(job)
    job.set_stage("decode")
    sid = song_id_for(src)
    if library.is_complete(sid) and not opts.get("force"):
        job.song_id = sid
        return sid                                      # כבר נותח — מחזירים מהספרייה

    cancel = job.cancel
    sdir = library.song_dir(sid)
    sdir.mkdir(parents=True, exist_ok=True)
    info = audio.probe(src)
    has_cover = audio.extract_cover(src, sdir / "cover.jpg")
    y22 = audio.load_mono(src, 22050, cancel)
    dur = round(len(y22) / 22050, 3)

    doc = {
        "id": sid, "doc_version": DOC_VERSION, "engine_version": __version__,
        "created": time.time(), "modified": None,
        "source": {"path": str(src.resolve()), "name": src.name, "size": src.stat().st_size,
                   "ext": src.suffix.lower(), "is_video": info["is_video"]},
        "analysis_options": {k: v for k, v in opts.items() if k != "lyrics_text"},
        "analysis_state": "media", "transcribed_until": 0.0,
        "meta": {
            "title": info["title"] or src.stem, "artist": info["artist"], "album": info["album"],
            "track": info["track"], "year": info["year"], "genre": info["genre"],
            "folder": opts.get("folder", ""), "has_cover": has_cover,
            "duration": dur, "tempo": None, "time_signature": "4/4",
            "key": None, "key_confidence": 0.0, "language": opts["language"],
        },
        "waveform": audio.waveform(y22),
        "timeline": [], "beats": [], "recognized_words": [], "transcript_segments": [],
        "words": [], "lyrics_text": "", "lyrics_source": "none", "sections": [], "lines": [],
    }

    def publish(state: str):
        doc["analysis_state"] = state
        library.save(doc, touch=False)
        job.song_id = sid
        job.partial += 1
        job.set_stage(job.stage, job.stage_progress)     # מעורר את ה-SSE

    with tempfile.TemporaryDirectory(prefix="chords_") as td:
        td = Path(td)
        wav22 = audio.write_wav(y22, 22050, td / "a22.wav")
        if src.suffix.lower() not in BROWSER_PLAYABLE:
            audio.write_wav(y22, 22050, sdir / "play.wav")   # mkv/avi/wma: הנגן בממשק לא מכיר
        del y22
        publish("media")
        cancel.check()

        job.set_stage("chords")
        raw = chords.recognize(wav22, opts["chord_vocabulary"], cancel,
                               progress=lambda f: job.set_stage("chords", f))
        cancel.check()
        job.set_stage("beats")
        bt = chords.beats(wav22)
        segs = chords.clean(raw, bt["beats"], opts["min_chord_duration"], opts["snap_to_beats"])
        key, key_conf = theory.detect_key(chords.timeline(segs))
        doc["meta"].update(tempo=bt["tempo"], key=key.name() if key else None, key_confidence=key_conf)
        doc["timeline"] = [{"start": s["start"], "end": s["end"], "label": theory.parse(s["label"]).to_harte()} for s in segs]
        doc["beats"] = bt["beats"]
        layout(doc)
        publish("chords")
        cancel.check()

        if not opts["skip_lyrics"]:
            voice_src = src
            if "vocals" not in job.skipped:
                job.set_stage("vocals")
                voice_src = audio.separate_vocals(wav22, td, cancel)
            wav16 = audio.decode(voice_src, td / "a16.wav", 16000, cancel)
            job.set_stage("lyrics")
            live: list[dict] = []
            last_pub = [0.0]

            def on_segment(line: str):
                m = _SEG_RE.match(line.strip())
                if not m or not m.group(7).strip():
                    return
                live.append({"start": _secs(*m.group(1, 2, 3)), "end": _secs(*m.group(4, 5, 6)),
                             "text": m.group(7).strip()})
                doc["transcribed_until"] = live[-1]["end"]
                if time.time() - last_pub[0] > 2.5:
                    last_pub[0] = time.time()
                    doc["recognized_words"] = _rough_words(live)
                    layout(doc)
                    publish("lyrics")

            tr = lyrics.transcribe(wav16, opts, cancel, progress=lambda f: job.set_stage("lyrics", f),
                                   on_line=on_segment)
            doc["recognized_words"], doc["transcript_segments"] = tr["words"], tr["segments"]

        job.set_stage("align")
        layout(doc, opts.get("lyrics_text", ""))
        doc["transcribed_until"] = dur
        doc["analysis_state"] = "done"
    library.save_analysis(doc)
    job.song_id = sid
    return sid


def layout(doc: dict, lyrics_text: str = "") -> dict:
    """בונה את השורות מחדש מהמילים שזוהו ומציר האקורדים — בלי לנתח שוב את השמע.
    lyrics_text: מילים נכונות (שורה = שורה, שורה ריקה = בית חדש); ריק = לפי התמלול."""
    known_lines = None
    words = doc.get("recognized_words", [])
    if lyrics_text.strip():
        al = lyrics.align_known_lyrics(words, lyrics_text)
        words, known_lines = al["words"], al["lines"]
    lines = align.build_lines(words, known_lines)
    all_lines = align.attach_chords(lines, doc["timeline"], doc["meta"]["duration"], doc["beats"])
    doc["words"] = words
    doc["lyrics_text"] = lyrics_text if known_lines else ""
    doc["lyrics_source"] = "user" if known_lines else ("transcript" if words else "none")
    doc["sections"] = align.mark_sections(all_lines)
    doc["lines"] = all_lines
    return doc
