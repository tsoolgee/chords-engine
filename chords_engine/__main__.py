"""שורת פקודה:
  python -m chords_engine serve [--port 8765]
  python -m chords_engine analyze song.mp3 [--out תיקייה] [--transpose 2] [--capo 3] [--skip-lyrics] [--lyrics lyrics.txt]
  python -m chords_engine chord "D/F#"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import config, library, render, theory

BOM = chr(0xFEFF)  # פנקס רשימות מזהה UTF-8 לפיו


def _analyze(a):
    from .jobs import Job
    from .pipeline import analyze
    opts = {"skip_lyrics": a.skip_lyrics, "accurate_timing": a.accurate, "force": a.force,
            "separate_vocals": a.vocals}
    if a.model:
        opts["whisper_model"] = a.model
    if a.lyrics:
        opts["lyrics_text"] = Path(a.lyrics).read_text(encoding="utf-8")
    if a.prompt:
        opts["prompt"] = a.prompt
    if a.relayout:
        from .pipeline import layout, song_id_for
        sid = song_id_for(Path(a.file))
        doc = library.load(sid)
        layout(doc, opts.get("lyrics_text", ""))
        library.save(doc)
        return _output(a, sid)
    job = Job(id="cli", path=a.file, options=opts)
    t0 = time.time()
    last = [None]

    def show():
        while job.status not in ("done", "error"):
            if (job.stage_label, int(job.progress * 100)) != last[0]:
                last[0] = (job.stage_label, int(job.progress * 100))
                print(f"\r{int(job.progress * 100):3d}%  {job.stage_label:<30}", end="", file=sys.stderr, flush=True)
            time.sleep(0.3)

    import threading
    threading.Thread(target=show, daemon=True).start()
    job.status = "running"
    try:
        sid = analyze(job)
    finally:
        job.status = "done"
    print(f"\rהסתיים תוך {time.time() - t0:.0f} שניות. מזהה שיר: {sid}" + " " * 20, file=sys.stderr)
    _output(a, sid)


def _output(a, sid):
    view = render.render(library.load(sid), {"transpose": a.transpose, "capo": a.capo, "simplify": a.simplify,
                                             "notation": a.notation})
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(a.file).stem
        (out / f"{stem}.json").write_text(json.dumps(view, ensure_ascii=False, indent=1), encoding="utf-8")
        for fmt, (fn, _, ext) in render.EXPORTERS.items():
            (out / f"{stem}{ext}").write_text(BOM + fn(view), encoding="utf-8")
        print(f"נשמר ב-{out}", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(render.to_text(view))


def main(argv=None):
    p = argparse.ArgumentParser(prog="chords_engine")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="שרת API מקומי ל-UI")
    s.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    s.add_argument("--host", default="127.0.0.1")
    a = sub.add_parser("analyze", help="ניתוח קובץ שמע")
    a.add_argument("file")
    a.add_argument("--out")
    a.add_argument("--transpose", type=int, default=0)
    a.add_argument("--capo", type=int, default=0)
    a.add_argument("--simplify", default="standard", choices=["basic", "standard", "full"])
    a.add_argument("--notation", default="letters", choices=["letters", "solfege_he", "solfege"])
    a.add_argument("--skip-lyrics", action="store_true")
    a.add_argument("--accurate", action="store_true", help="תזמון מילים מדויק (DTW), איטי יותר")
    a.add_argument("--vocals", action="store_true", help="הפרדת שירה עם demucs לפני התמלול")
    a.add_argument("--lyrics", help="קובץ טקסט עם המילים הנכונות")
    a.add_argument("--prompt")
    a.add_argument("--model")
    a.add_argument("--force", action="store_true", help="לנתח מחדש גם אם השיר כבר בספרייה")
    a.add_argument("--relayout", action="store_true", help="רק לבנות שורות מחדש מהניתוח השמור (פיתוח)")
    sub.add_parser("app", help="התוכנה המלאה עם חלון")
    c = sub.add_parser("chord", help="מידע על אקורד")
    c.add_argument("name")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8")
    if args.cmd == "app":
        from .desktop import main as app_main
        app_main()
    elif args.cmd == "serve":
        from .server import serve
        serve(args.host, args.port)
    elif args.cmd == "analyze":
        _analyze(args)
    elif args.cmd == "chord":
        ch = theory.parse(args.name)
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"label": ch.to_harte(), "name": theory.format_chord(ch),
                          "guitar": theory.guitar_shapes(ch), "piano": theory.piano_notes(ch)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
