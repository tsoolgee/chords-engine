"""בדיקות מהירות (בלי whisper): תורת המוזיקה, שיבוץ אקורדים, עריכות, ייצוא, ושרת ה-API
על שיר סינתטי שהאקורדים שלו ידועים.  הרצה:  python -m unittest discover tests"""
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="chords_test_"))
os.environ["CHORDS_DATA"] = str(TMP)          # ספרייה נפרדת לבדיקות

from chords_engine import align, editing, lyrics, render, theory  # noqa: E402

PROGRESSION = ["C", "G", "Am", "F", "C", "D7", "G", "Em"]


def make_song(path: Path, seconds_per_chord=2.0, sr=22050):
    import numpy as np
    import soundfile as sf
    notes = {"C": [48, 52, 55, 60, 64], "G": [43, 47, 50, 55, 59], "Am": [45, 52, 57, 60, 64],
             "F": [41, 48, 53, 57, 60], "D7": [50, 54, 57, 60, 66], "Em": [40, 47, 52, 55, 59]}
    out = []
    for c in PROGRESSION:
        t = np.arange(int(sr * seconds_per_chord)) / sr
        y = sum(sum((0.5 ** h) * np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * (h + 1) * t) for h in range(4))
                for m in notes[c])
        out.append(y * np.exp(-t * 0.8))
    y = np.concatenate(out)
    sf.write(str(path), y / np.abs(y).max() * 0.8, sr)


class TheoryTests(unittest.TestCase):
    def test_parse_formats(self):
        cases = {"A:min7/b7": "Am7/G", "C:sus4(b7)": "C7sus4", "D/F#": "D/F#", "Bbmaj7": "A#maj7",
                 "E:hdim7": "Em7b5", "לה m7": "Am7", "סול/סי": "G/B", "N": "N.C."}
        for src, want in cases.items():
            self.assertEqual(theory.format_chord(theory.parse(src)), want, src)
        with self.assertRaises(ValueError):
            theory.parse("H7")

    def test_transpose_and_spelling(self):
        key = theory.parse_key("F")
        f = theory.flat_policy(key)
        self.assertEqual(theory.format_chord(theory.parse("A#"), "letters", f), "Bb")
        self.assertEqual(theory.format_chord(theory.parse("C").transpose(3), "letters",
                                             theory.flat_policy(theory.parse_key("Eb"))), "Eb")
        # V במינור נכתב בדיאז (E עם G#), bVII במז'ור בבמול
        self.assertEqual(theory.format_chord(theory.parse("G#"), "letters", theory.flat_policy(theory.parse_key("Am"))), "G#")
        self.assertEqual(theory.format_chord(theory.parse("A#"), "letters", theory.flat_policy(theory.parse_key("C"))), "Bb")

    def test_key_detection(self):
        tl = [(i * 2.0, i * 2.0 + 2, theory.parse(c)) for i, c in enumerate(PROGRESSION)]
        key, conf = theory.detect_key(tl)
        self.assertEqual(key.name(), "C")
        tl = [(i * 2.0, i * 2.0 + 2, theory.parse(c)) for i, c in enumerate(["Am", "Dm", "E7", "Am", "F", "G", "E", "Am"])]
        self.assertEqual(theory.detect_key(tl)[0].name(), "Am")

    def test_capo(self):
        tl = [(i, i + 1, theory.parse(c)) for i, c in enumerate(["Ab", "Eb", "Fm", "Db"])]
        best = theory.suggest_capo(tl)[0]
        self.assertEqual(best["capo"], 1)            # G D Em C — הכל פתוח
        self.assertEqual(best["hard_ratio"], 0.0)

    def test_guitar_shapes(self):
        self.assertEqual(theory.guitar_shapes(theory.parse("G/B"))[0]["frets"], [None, 2, 0, 0, 0, 3])
        self.assertEqual(theory.guitar_shapes(theory.parse("F/A"))[0]["frets"], [None, 0, 3, 2, 1, 1])
        self.assertEqual(theory.guitar_shapes(theory.parse("Bm"))[0]["frets"], [None, 2, 4, 4, 3, 2])
        for q in theory.QUALITIES:
            for root in range(12):
                ch = theory.Chord(root, q)
                for shape in theory.guitar_shapes(ch):
                    pcs = {(theory.STRINGS_PC[i] + f) % 12 for i, f in enumerate(shape["frets"]) if f is not None}
                    self.assertTrue(pcs <= set(ch.pitch_classes()), f"{theory.format_chord(ch)} {shape}")


def _words(spec):
    """spec: [(text, start, end, segment)]"""
    return [{"text": t, "start": s, "end": e, "p": 1.0, "segment": g} for t, s, e, g in spec]


class AlignTests(unittest.TestCase):
    def setUp(self):
        self.words = _words([("שלום", 4.0, 4.5, 0), ("לך", 4.5, 5.0, 0), ("עולם", 5.0, 5.9, 0),
                             ("מה", 6.2, 6.5, 1), ("נשמע", 6.5, 7.5, 1)])
        self.chords = [{"start": 0.0, "end": 4.0, "label": "C:maj"}, {"start": 4.0, "end": 5.0, "label": "A:min"},
                       {"start": 5.0, "end": 6.2, "label": "F:maj"}, {"start": 6.2, "end": 12.0, "label": "G:maj"}]

    def test_attach(self):
        lines = align.build_lines(self.words)
        out = align.attach_chords(lines, self.chords, 12.0, [i * 0.5 for i in range(24)])
        align.mark_sections(out)
        self.assertEqual(out[0]["type"], "instrumental")
        self.assertEqual(out[0]["role"], "intro")
        l1 = out[1]
        self.assertEqual([(c["label"], c["char"]) for c in l1["chords"]], [("A:min", 0), ("F:maj", 8)])
        l2 = out[2]
        self.assertEqual([(c["label"], c["char"]) for c in l2["chords"]], [("G:maj", 0)])
        self.assertEqual(out[-1]["role"], "outro")

    def test_known_lyrics(self):
        al = lyrics.align_known_lyrics(self.words, "שָׁלוֹם לך עולם\n\nמה נשמע חבר")
        self.assertEqual([l["stanza_break"] for l in al["lines"]], [False, True])
        w = {x["text"]: x for x in al["words"]}
        self.assertEqual(w["שָׁלוֹם"]["start"], 4.0)     # ניקוד לא מפריע להתאמה
        self.assertGreaterEqual(w["חבר"]["start"], 7.5)  # מילה שלא זוהתה -> אינטרפולציה


class RenderEditTests(unittest.TestCase):
    def doc(self):
        lines = align.build_lines(_words([("שלום", 1.0, 1.5, 0), ("עולם", 1.5, 2.5, 0)]))
        out = align.attach_chords(lines, [{"start": 1.0, "end": 3.0, "label": "C:maj"}], 3.0, [])
        return {"id": "abc", "meta": {"key": "C", "title": "t", "artist": "", "tempo": 100, "duration": 3.0},
                "timeline": [{"start": 1.0, "end": 3.0, "label": "C:maj"}], "sections": align.mark_sections(out),
                "lines": out}

    def test_edit_in_transposed_view(self):
        d = self.doc()
        v = render.render(d, {"transpose": 2})
        self.assertEqual(v["lines"][0]["chords"][0]["name"], "D")
        v["lines"][0]["chords"][0]["name"] = "Em"             # המשתמש רואה D ומחליף ל-Em
        new = editing.apply_edits(d, {"view": {"transpose": 2}, "lines": v["lines"]})
        self.assertEqual(new["lines"][0]["chords"][0]["label"], "D:min")
        self.assertEqual(render.render(new)["lines"][0]["chords"][0]["name"], "Dm")

    def test_exports(self):
        v = render.render(self.doc(), {"capo": 2})
        self.assertIn("[Bb]שלום", render.to_chordpro(v))    # C עם קאפו 2 = צורת Bb
        self.assertIn("{capo: 2}", render.to_chordpro(v))
        self.assertIn("שלום עולם", render.to_text(v))
        self.assertTrue(render.to_lrc(v).startswith("[ti:t]"))


class ServerTests(unittest.TestCase):
    """מריץ את השרת האמיתי על פורט פנוי ומנתח שיר סינתטי (אקורדים בלבד)."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from chords_engine import server
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/api"
        cls.song = TMP / "synth.wav"
        make_song(cls.song)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_full_flow(self):
        st, cfg = self.call("GET", "/config")
        self.assertEqual(st, 200)
        st, job = self.call("POST", "/analyze", {"path": str(self.song), "options": {"skip_lyrics": True}})
        self.assertEqual(st, 202)
        self.assertNotIn("lyrics", [s["id"] for s in job["stages"]])
        for _ in range(600):
            st, job = self.call("GET", f"/jobs/{job['id']}")
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.5)
        self.assertEqual(job["status"], "done", job.get("error"))
        sid = job["song_id"]
        st, song = self.call("GET", f"/songs/{sid}")
        names = [t["name"] for t in song["timeline"] if t["name"] != "N.C."]
        self.assertEqual(names, PROGRESSION)
        self.assertEqual(song["meta"]["key"], "C")
        st, song = self.call("GET", f"/songs/{sid}?transpose=-2&capo=0")
        self.assertEqual(song["meta"]["key"], "Bb")
        st, err = self.call("PUT", f"/songs/{sid}", {"lines": [{"type": "lyric", "text": "x", "chords": [{"name": "Q"}]}]})
        self.assertEqual(st, 400)
        st, song = self.call("POST", f"/songs/{sid}/reset")
        self.assertEqual(st, 200)
        st, _ = self.call("GET", "/songs/0000000000000000")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
