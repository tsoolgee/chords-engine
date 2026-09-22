"""מוריד ומכין את מה שלא נכנס ל-git: whisper.cpp ומודל העברית של ivrit-ai.
הרצה:  python scripts/setup_vendor.py   (אפשר להריץ שוב; מה שכבר קיים מדולג)"""
from __future__ import annotations

import io
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
WHISPER_TAG = "b5130"
WHISPER_ZIP = f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_TAG}/whisper-bin-x64.zip"
MODEL_URL = "https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ggml/resolve/main/ggml-model.bin"
MODEL_SIZE = 1624555275
MODEL = VENDOR / "models" / "ggml-ivrit-large-v3-turbo.bin"
MODEL_Q = VENDOR / "models" / "ggml-ivrit-large-v3-turbo-q5_0.bin"
CLI = VENDOR / "whisper" / "Release" / "whisper-cli.exe"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main():
    if not CLI.exists():
        print("מוריד whisper.cpp", WHISPER_TAG)
        data = fetch(WHISPER_ZIP)
        if not data.startswith(b"PK"):
            sys.exit("ההורדה של whisper.cpp נחסמה (נטפרי?). צריך להוריד ידנית: " + WHISPER_ZIP)
        zipfile.ZipFile(io.BytesIO(data)).extractall(VENDOR / "whisper")

    MODEL.parent.mkdir(parents=True, exist_ok=True)
    if not MODEL_Q.exists():
        if not MODEL.exists() or MODEL.stat().st_size != MODEL_SIZE:
            print("מוריד את מודל העברית (1.6GB) — אפשר לעצור ולהמשיך מאוחר יותר")
            # curl יודע להמשיך הורדה שנקטעה (-C -); זה קרה בפועל מאחורי נטפרי
            subprocess.run(["curl", "-L", "-C", "-", "-o", str(MODEL), MODEL_URL], check=True)
        if MODEL.stat().st_size != MODEL_SIZE or MODEL.read_bytes()[:4] != b"lmgg":
            sys.exit("קובץ המודל לא תקין — כנראה חסימה. למחוק ולנסות שוב.")
        print("מכווץ ל-q5_0 (מהיר פי 1.5, 550MB)")
        subprocess.run([str(CLI.parent / "whisper-quantize.exe"), str(MODEL), str(MODEL_Q), "q5_0"], check=True)
    print("מוכן:", MODEL_Q)


if __name__ == "__main__":
    main()
