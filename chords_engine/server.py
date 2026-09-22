"""שרת HTTP מקומי (127.0.0.1) — הממשק הגרפי מדבר רק איתו. התיעוד המלא: docs/API.md."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import __version__, audio, config, library, pipeline, render, theory
from .editing import apply_edits
from .jobs import JobQueue

BOM = chr(0xFEFF)  # פנקס רשימות מזהה UTF-8 לפיו

QUEUE = JobQueue(pipeline.analyze, pipeline.plan)
LAST_PING = [time.time()]
UI_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
               ".flac": "audio/flac", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
               ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _song_or_404(sid: str) -> dict:
    try:
        return library.load(sid)
    except KeyError:
        raise ApiError(404, "השיר לא נמצא")


def _job_or_404(jid: str):
    job = QUEUE.jobs.get(jid)
    if not job:
        raise ApiError(404, "העבודה לא נמצאה")
    return job


def _submit(path: str, options: dict):
    if not path or not Path(path).is_file():
        raise ApiError(400, f"הקובץ לא נמצא: {path}")
    unknown = set(options) - set(config.DEFAULT_ANALYZE_OPTIONS) - {"force"}
    if unknown:
        raise ApiError(400, f"אפשרויות לא מוכרות: {', '.join(sorted(unknown))}")
    return QUEUE.submit(str(Path(path).resolve()), options)


class Handler(BaseHTTPRequestHandler):
    server_version = f"ChordsEngine/{__version__}"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ תשתית
    def log_message(self, fmt, *args):
        if os.environ.get("CHORDS_LOG"):
            super().log_message(fmt, *args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename, Range")
        self.send_header("Access-Control-Expose-Headers", "Content-Disposition, Content-Range")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            raise ApiError(400, "גוף הבקשה אינו JSON תקין")

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        u = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        for pattern, meth, fn in ROUTES:
            m = re.fullmatch(pattern, u.path)
            if m and meth == method:
                try:
                    fn(self, q, *m.groups())
                except ApiError as e:
                    self._json({"error": str(e)}, e.status)
                except (ValueError, KeyError) as e:
                    self._json({"error": str(e)}, 400)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    self._json({"error": f"שגיאה פנימית: {e}"}, 500)
                return
        self._json({"error": "נתיב לא קיים"}, 404)

    # ------------------------------------------------------------ מערכת
    def ui(self, q, rel="index.html"):
        p = (config.UI_DIR / (rel or "index.html")).resolve()
        if config.UI_DIR.resolve() not in p.parents or not p.is_file():
            raise ApiError(404, "לא נמצא")
        self._send(200, p.read_bytes(), UI_TYPES.get(p.suffix, "application/octet-stream"),
                   {"Cache-Control": "no-cache"})

    def root(self, q):
        self.send_response(302)
        self.send_header("Location", "/ui/index.html")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def ping(self, q):
        LAST_PING[0] = time.time()
        self._json({"ok": True})

    def import_paths(self, q):
        """קבצים ו/או תיקיות. תיקייה נסרקת לעומק, ושם התיקייה הופך לתיקייה בספרייה."""
        b = self._body()
        opts = dict(b.get("options") or {})
        base_folder = (b.get("folder") or "").strip("/")
        jobs = []
        for raw in b.get("paths") or []:
            p = Path(raw)
            if p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file() and f.suffix.lower() in audio.AUDIO_EXT:
                        rel = f.parent.relative_to(p.parent).as_posix()
                        folder = "/".join(x for x in (base_folder, rel) if x)
                        jobs.append(_submit(str(f), {**opts, "folder": folder}).public())
            elif p.is_file():
                jobs.append(_submit(str(p), {**opts, "folder": opts.get("folder") or base_folder}).public())
        if not jobs:
            raise ApiError(400, "לא נמצאו קבצי שמע או וידאו")
        self._json(jobs, 202)

    def cover(self, q, sid):
        p = library.song_dir(sid) / "cover.jpg"
        if not p.exists():
            raise ApiError(404, "אין תמונה")
        data = p.read_bytes()
        ctype = "image/png" if data[1:4] == b"PNG" else "image/jpeg"
        self._send(200, data, ctype, {"Cache-Control": "max-age=3600"})

    def health(self, q):
        self._json({"ok": True, "version": __version__, "time": time.time()})

    def get_config(self, q):
        self._json({
            "version": __version__,
            "analyze_defaults": config.DEFAULT_ANALYZE_OPTIONS,
            "view_defaults": render.DEFAULT_VIEW,
            "whisper_models": config.available_models(),
            "whisper_ready": config.WHISPER_CLI.exists() and bool(config.available_models()),
            "vad_available": config.vad_model_path() is not None,
            "demucs_available": audio.demucs_available(),
            "chord_vocabularies": ["submission", "ismir2017", "full"],
            "library_dir": str(config.LIBRARY_DIR),
        })

    # ------------------------------------------------------------ עבודות
    def analyze(self, q):
        b = self._body()
        job = _submit(b.get("path", ""), b.get("options") or {})
        self._json(job.public(), 202)

    def upload(self, q):
        name = Path(unquote(self.headers.get("X-Filename") or "upload.bin")).name
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ApiError(400, "קובץ ריק")
        d = config.DATA_DIR / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        dst = d / f"{int(time.time())}_{name}"
        with open(dst, "wb") as f:
            left = n
            while left:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        self._json({"path": str(dst)}, 201)

    def list_jobs(self, q):
        self._json([j.public() for j in sorted(QUEUE.jobs.values(), key=lambda j: -j.created)])

    def get_job(self, q, jid):
        self._json(_job_or_404(jid).public())

    def cancel_job(self, q, jid):
        _job_or_404(jid)
        self._json({"cancelled": QUEUE.cancel(jid)})

    def job_events(self, q, jid):
        """Server-Sent Events: הודעה בכל שינוי בהתקדמות, נסגר כשהעבודה מסתיימת."""
        job = _job_or_404(jid)
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        seen = -1
        try:
            while True:
                with QUEUE.cond:
                    if job.version == seen:
                        QUEUE.cond.wait(timeout=1.0)
                if job.version != seen:
                    seen = job.version
                    self.wfile.write(f"data: {json.dumps(job.public(), ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                if job.status in ("done", "error", "cancelled"):
                    break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    # ------------------------------------------------------------ שירים
    def list_songs(self, q):
        self._json(library.list_songs())

    def search(self, q):
        """חיפוש בתוך מילות השירים. מחזיר מזהי שירים."""
        from .lyrics import normalize_word
        needle = " ".join(normalize_word(w) for w in q.get("q", "").split())
        hits = []
        if needle and config.LIBRARY_DIR.exists():
            for d in config.LIBRARY_DIR.iterdir():
                p = d / "song.json"
                if not p.exists():
                    continue
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                text = " ".join(normalize_word(w) for l in doc["lines"] for w in l.get("text", "").split())
                if needle in text:
                    hits.append(doc["id"])
        self._json(hits)

    def get_song(self, q, sid):
        self._json(render.render(_song_or_404(sid), q))

    def get_song_raw(self, q, sid):
        self._json(_song_or_404(sid))

    def put_song(self, q, sid):
        doc = _song_or_404(sid)
        body = self._body()
        new = apply_edits(doc, body)
        library.save(new)
        self._json(render.render(new, body.get("view") or q))

    def reset_song(self, q, sid):
        _song_or_404(sid)
        try:
            doc = library.reset(sid)
        except KeyError:
            raise ApiError(409, "הניתוח עוד לא הסתיים")
        self._json(render.render(doc, self._body().get("view") or q))

    def delete_song(self, q, sid):
        _song_or_404(sid)
        library.delete(sid)
        self._json({"deleted": sid})

    def reanalyze(self, q, sid):
        doc = _song_or_404(sid)
        opts = {**doc.get("analysis_options", {}), **(self._body().get("options") or {}), "force": True}
        opts = {k: v for k, v in opts.items() if k in config.DEFAULT_ANALYZE_OPTIONS or k == "force"}
        self._json(_submit(doc["source"]["path"], opts).public(), 202)

    def set_lyrics(self, q, sid):
        """מילים נכונות שהמשתמש הדביק -> יישור לזמנים ובניית השורות מחדש (בלי לנתח שוב).
        text ריק = חזרה למילים של התמלול. דורס עריכות ידניות של השורות."""
        doc = _song_or_404(sid)
        body = self._body()
        pipeline.layout(doc, body.get("text") or "")
        library.save(doc)
        self._json(render.render(doc, body.get("view") or q))

    def export(self, q, sid):
        doc = _song_or_404(sid)
        fmt = q.get("format", "txt")
        view = render.render(doc, q)
        title = doc["meta"].get("title") or sid
        if fmt == "json":
            body, ctype, ext = json.dumps(view, ensure_ascii=False, indent=1).encode("utf-8"), "application/json; charset=utf-8", ".json"
        elif fmt == "csv":
            rows = ["start,end,chord"] + [f"{t['start']},{t['end']},{t['name']}" for t in view["timeline"]]
            rows += ["", "start,end,line"] + [f"{l['start']},{l['end']},\"{l.get('text', '').replace(chr(34), chr(39))}\""
                                             for l in view["lines"] if l["type"] == "lyric"]
            body, ctype, ext = (BOM + chr(10).join(rows)).encode("utf-8"), "text/csv; charset=utf-8", ".csv"
        elif fmt in render.EXPORTERS:
            fn, ctype, ext = render.EXPORTERS[fmt]
            body = (BOM + fn(view)).encode("utf-8")   # BOM: פנקס רשימות יזהה UTF-8
        else:
            raise ApiError(400, f"פורמט לא מוכר: {fmt}")
        fname = quote(f"{title}{ext}")
        self._send(200, body, ctype, {"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})

    def song_audio(self, q, sid):
        """קובץ השמע המקורי, עם תמיכה ב-Range (דילוג בנגן)."""
        p = library.song_dir(sid) / "play.wav"
        if not p.exists():
            p = Path(_song_or_404(sid)["source"]["path"])
        if not p.exists():
            raise ApiError(404, "קובץ השמע המקורי הוזז או נמחק")
        size = p.stat().st_size
        ctype = AUDIO_TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        start, end = 0, size - 1
        if rng:
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
        end = min(end, size - 1)
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(p, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(left, 256 * 1024))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ------------------------------------------------------------ אקורד בודד
    def chord_info(self, q):
        """לחלון עריכת אקורד: מפענח שם, מחזיר תצוגה ואצבועים."""
        ch = theory.parse(q.get("name", ""))
        notation = q.get("notation", "letters")
        flats = q.get("accidentals") == "flats"
        self._json({"label": ch.to_harte(), "name": theory.format_chord(ch, notation, flats),
                    "guitar": theory.guitar_shapes(ch, int(q.get("limit", 3))),
                    "piano": theory.piano_notes(ch),
                    "notes": [theory.note_name(pc, notation, flats) for pc in ch.pitch_classes()]})

    def chord_vocabulary(self, q):
        notation = q.get("notation", "letters")
        self._json({
            "roots": [{"pc": i, "sharp": theory.note_name(i, notation, False), "flat": theory.note_name(i, notation, True)} for i in range(12)],
            "qualities": [{"id": k, "suffix": v[0], "intervals": v[1]} for k, v in theory.QUALITIES.items()],
        })


ROUTES = [
    (r"/", "GET", Handler.root),
    (r"/ui/?", "GET", Handler.ui),
    (r"/ui/([\w./-]+)", "GET", Handler.ui),
    (r"/api/ping", "GET", Handler.ping),
    (r"/api/library/import", "POST", Handler.import_paths),
    (r"/api/songs/([0-9a-f]+)/cover", "GET", Handler.cover),
    (r"/api/health", "GET", Handler.health),
    (r"/api/config", "GET", Handler.get_config),
    (r"/api/analyze", "POST", Handler.analyze),
    (r"/api/upload", "POST", Handler.upload),
    (r"/api/jobs", "GET", Handler.list_jobs),
    (r"/api/jobs/([0-9a-f]+)", "GET", Handler.get_job),
    (r"/api/jobs/([0-9a-f]+)/cancel", "POST", Handler.cancel_job),
    (r"/api/jobs/([0-9a-f]+)/events", "GET", Handler.job_events),
    (r"/api/songs", "GET", Handler.list_songs),
    (r"/api/search", "GET", Handler.search),
    (r"/api/songs/([0-9a-f]+)", "GET", Handler.get_song),
    (r"/api/songs/([0-9a-f]+)", "PUT", Handler.put_song),
    (r"/api/songs/([0-9a-f]+)", "DELETE", Handler.delete_song),
    (r"/api/songs/([0-9a-f]+)/raw", "GET", Handler.get_song_raw),
    (r"/api/songs/([0-9a-f]+)/reset", "POST", Handler.reset_song),
    (r"/api/songs/([0-9a-f]+)/reanalyze", "POST", Handler.reanalyze),
    (r"/api/songs/([0-9a-f]+)/lyrics", "POST", Handler.set_lyrics),
    (r"/api/songs/([0-9a-f]+)/export", "GET", Handler.export),
    (r"/api/songs/([0-9a-f]+)/audio", "GET", Handler.song_audio),
    (r"/api/chord", "GET", Handler.chord_info),
    (r"/api/chords/vocabulary", "GET", Handler.chord_vocabulary),
]


def serve(host: str = "127.0.0.1", port: int = config.DEFAULT_PORT):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"ChordsEngine {__version__} מאזין ב-http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
