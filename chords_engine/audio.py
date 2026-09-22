"""פענוח אודיו ווידאו (PyAV — ffmpeg בתוך חבילת Python, בלי exe חיצוני),
Metadata, תמונת אלבום, צורת גל, והרצת תהליכים חיצוניים עם ביטול."""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np

from .jobs import Cancelled, CancelToken

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wma", ".aif", ".aiff",
             ".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".3gp", ".amr"}
VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".3gp"}


def run(cmd: list[str], cancel: CancelToken | None = None, on_line=None) -> str:
    """מריץ תהליך, מאפשר ביטול, ומעביר כל שורת פלט ל-on_line."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    if cancel:
        cancel.attach(proc)
    out = []
    try:
        buf = b""
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.replace(b"\r", b"\n").split(b"\n")
            for ln in lines:
                s = ln.decode("utf-8", "replace")
                out.append(s)
                if on_line:
                    on_line(s)
        proc.wait()
    finally:
        if cancel:
            cancel.detach(proc)
    if cancel and cancel.cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} נכשל ({proc.returncode}):\n" + "\n".join(out[-15:]))
    return "\n".join(out)


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_mono(src: Path, sr: int, cancel: CancelToken | None = None) -> np.ndarray:
    """כל פורמט -> float32 מונו בקצב sr."""
    import av
    chunks = []
    with av.open(str(src)) as c:
        if not c.streams.audio:
            raise ValueError("בקובץ אין ערוץ שמע")
        st = c.streams.audio[0]
        rs = av.AudioResampler(format="flt", layout="mono", rate=sr)
        for i, frame in enumerate(c.decode(st)):
            for f in rs.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
            if cancel and i % 500 == 0:
                cancel.check()
        for f in rs.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError("לא נמצא שמע בקובץ")
    return np.concatenate(chunks).astype(np.float32)


def write_wav(y: np.ndarray, sr: int, dst: Path) -> Path:
    import soundfile as sf
    sf.write(str(dst), y, sr, subtype="PCM_16")
    return dst


def decode(src: Path, dst: Path, sr: int, cancel: CancelToken | None = None) -> Path:
    return write_wav(load_mono(src, sr, cancel), sr, dst)


def duration(wav: Path) -> float:
    import soundfile as sf
    info = sf.info(str(wav))
    return info.frames / info.samplerate


def probe(src: Path) -> dict:
    """Metadata: שם, אמן, אלבום, רצועה, שנה, ז'אנר, משך, האם וידאו, האם יש תמונה."""
    import av
    out = {"title": "", "artist": "", "album": "", "track": "", "year": "", "genre": "",
           "duration": 0.0, "is_video": False, "has_cover": False}
    try:
        with av.open(str(src)) as c:
            tags = {k.lower(): v for k, v in (c.metadata or {}).items()}
            for s in c.streams.audio[:1]:
                for k, v in (s.metadata or {}).items():
                    tags.setdefault(k.lower(), v)
            out["title"] = tags.get("title", "")
            out["artist"] = tags.get("artist") or tags.get("album_artist", "")
            out["album"] = tags.get("album", "")
            out["track"] = (tags.get("track") or "").split("/")[0]
            out["year"] = (tags.get("date") or tags.get("year") or "")[:4]
            out["genre"] = tags.get("genre", "")
            out["duration"] = round((c.duration or 0) / 1_000_000, 3)
            for v in c.streams.video:
                if v.disposition & getattr(av.stream.Disposition, "attached_pic", 1024):
                    out["has_cover"] = True
                else:
                    out["is_video"] = True
    except Exception:  # noqa: BLE001 — קובץ פגום: מחזירים מה שיש
        pass
    return out


def extract_cover(src: Path, dst: Path) -> bool:
    """שומר את תמונת האלבום המוטמעת (אם יש)."""
    import av
    try:
        with av.open(str(src)) as c:
            for v in c.streams.video:
                if v.disposition & getattr(av.stream.Disposition, "attached_pic", 1024):
                    pkt = next(c.demux(v))
                    data = bytes(pkt)
                    if data:
                        dst.write_bytes(data)
                        return True
    except Exception:  # noqa: BLE001
        pass
    return False


def waveform(y: np.ndarray, points: int = 1200) -> list[float]:
    """שיאים מנורמלים 0..1 לציור צורת הגל."""
    if len(y) == 0:
        return []
    n = max(1, len(y) // points)
    trimmed = np.abs(y[: n * (len(y) // n)]).reshape(-1, n).max(axis=1)
    peak = float(trimmed.max()) or 1.0
    return [round(float(v) / peak, 3) for v in trimmed[:points]]


def demucs_available() -> bool:
    return importlib.util.find_spec("demucs") is not None and not getattr(sys, "frozen", False)


def separate_vocals(src: Path, workdir: Path, cancel: CancelToken | None = None, on_line=None) -> Path:
    """מפריד שירה עם demucs (htdemucs, two-stems). מחזיר נתיב לקובץ השירה."""
    out = workdir / "demucs"
    run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
         "-o", str(out), str(src)], cancel, on_line)
    hits = list(out.rglob("vocals.wav"))
    if not hits:
        raise RuntimeError("demucs לא יצר vocals.wav")
    return hits[0]
