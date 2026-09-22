"""תור עבודות: עבודה אחת רצה בכל רגע (המעבד חלש), התקדמות וביטול."""
from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable


class Cancelled(Exception):
    pass


class CancelToken:
    def __init__(self):
        self.cancelled = False
        self._procs = set()
        self._lock = threading.Lock()

    def cancel(self):
        self.cancelled = True
        with self._lock:
            for p in list(self._procs):
                try:
                    p.kill()
                except OSError:
                    pass

    def attach(self, proc):
        with self._lock:
            self._procs.add(proc)
            if self.cancelled:
                proc.kill()

    def detach(self, proc):
        with self._lock:
            self._procs.discard(proc)

    def check(self):
        if self.cancelled:
            raise Cancelled()


# שלבי העבודה ומשקלם היחסי בפס ההתקדמות
STAGES = [
    ("decode", "מפענח את קובץ השמע", 3),
    ("chords", "מזהה אקורדים", 17),
    ("beats", "מזהה קצב ופעמות", 5),
    ("vocals", "מפריד שירה", 15),
    ("lyrics", "מתמלל מילים", 55),
    ("align", "משבץ אקורדים מעל המילים", 5),
]


@dataclass
class Job:
    id: str
    path: str
    options: dict
    status: str = "queued"          # queued | running | done | error | cancelled
    stage: str = ""
    stage_label: str = ""
    stage_progress: float = 0.0     # 0..1 בתוך השלב
    progress: float = 0.0           # 0..1 כולל
    song_id: str | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    cancel: CancelToken = field(default_factory=CancelToken)
    skipped: set = field(default_factory=set)
    version: int = 0
    partial: int = 0                # גדל בכל פעם שנשמרה תוצאה חלקית של השיר
    on_change: Callable[[], None] | None = field(default=None, repr=False)

    def set_stage(self, stage: str, frac: float = 0.0):
        self.stage = stage
        self.stage_label = next(l for s, l, _ in STAGES if s == stage)
        self.stage_progress = max(0.0, min(1.0, frac))
        active = [(s, w) for s, _, w in STAGES if s not in self.skipped]
        total = sum(w for _, w in active)
        done = 0.0
        for s, w in active:
            if s == stage:
                done += w * self.stage_progress
                break
            done += w
        self.progress = round(done / total, 4)
        self.version += 1
        if self.on_change:
            self.on_change()

    def public(self) -> dict:
        return {
            "id": self.id, "path": self.path, "status": self.status, "stage": self.stage,
            "stage_label": self.stage_label, "stage_progress": round(self.stage_progress, 3),
            "progress": self.progress, "song_id": self.song_id, "error": self.error, "partial": self.partial,
            "options": {k: v for k, v in (self.options or {}).items() if k != "lyrics_text"},
            "created": self.created, "finished": self.finished,
            "stages": [{"id": s, "label": l} for s, l, _ in STAGES if s not in self.skipped],
        }


class JobQueue:
    def __init__(self, worker: Callable[[Job], str], planner: Callable[[Job], None] | None = None):
        self._worker = worker
        self._planner = planner
        self._q: "queue.Queue[Job]" = queue.Queue()
        self.jobs: dict[str, Job] = {}
        self.cond = threading.Condition()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, path: str, options: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], path=path, options=options, on_change=self.notify)
        if self._planner:
            self._planner(job)
        self.jobs[job.id] = job
        self._q.put(job)
        self.notify()
        return job

    def notify(self):
        with self.cond:
            self.cond.notify_all()

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in ("done", "error", "cancelled"):
            return False
        job.cancel.cancel()
        if job.status == "queued":
            job.status = "cancelled"
        self.notify()
        return True

    def _loop(self):
        while True:
            job = self._q.get()
            if job.status == "cancelled":
                continue
            job.status = "running"
            self.notify()
            try:
                job.song_id = self._worker(job)
                job.status = "done"
                job.progress = 1.0
            except Cancelled:
                job.status = "cancelled"
            except Exception as e:     # noqa: BLE001 — השגיאה מוחזרת ל-UI
                job.status = "error"
                job.error = f"{e}"
                traceback.print_exc()
            job.finished = time.time()
            job.version += 1
            self.notify()
