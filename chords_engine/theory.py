"""תורת המוזיקה של המנוע: פענוח שמות אקורדים, טרנספוזיציה, פישוט, כתיב,
זיהוי סולם, המלצת קאפו ואצבוע לגיטרה/פסנתר.

ייצוג פנימי: Chord(root, quality, bass) — root/bass הם pitch class (0=C .. 11=B).
מקבל גם תוויות Harte של המודל (A:min7/b7) וגם שמות רגילים (Am7/G, C#m7b5, Bb).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
SOLFEGE_HE = ["דו", "דו#", "רה", "רה#", "מי", "פה", "פה#", "סול", "סול#", "לה", "לה#", "סי"]
SOLFEGE_HE_FLAT = ["דו", "רה♭", "רה", "מי♭", "מי", "פה", "סול♭", "סול", "לה♭", "לה", "סי♭", "סי"]
SOLFEGE = ["Do", "Do#", "Re", "Re#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]
SOLFEGE_FLAT = ["Do", "Reb", "Re", "Mib", "Mi", "Fa", "Solb", "Sol", "Lab", "La", "Sib", "Si"]

LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# איכויות קנוניות: סיומת תצוגה + מרווחים מהשורש
QUALITIES = {
    "maj":   ("",      [0, 4, 7]),
    "min":   ("m",     [0, 3, 7]),
    "7":     ("7",     [0, 4, 7, 10]),
    "maj7":  ("maj7",  [0, 4, 7, 11]),
    "min7":  ("m7",    [0, 3, 7, 10]),
    "9":     ("9",     [0, 4, 7, 10, 2]),
    "maj9":  ("maj9",  [0, 4, 7, 11, 2]),
    "min9":  ("m9",    [0, 3, 7, 10, 2]),
    "11":    ("11",    [0, 7, 10, 2, 5]),
    "13":    ("13",    [0, 4, 7, 10, 9]),
    "dim":   ("dim",   [0, 3, 6]),
    "dim7":  ("dim7",  [0, 3, 6, 9]),
    "hdim7": ("m7b5",  [0, 3, 6, 10]),
    "aug":   ("aug",   [0, 4, 8]),
    "sus2":  ("sus2",  [0, 2, 7]),
    "sus4":  ("sus4",  [0, 5, 7]),
    "7sus4": ("7sus4", [0, 5, 7, 10]),
    "6":     ("6",     [0, 4, 7, 9]),
    "min6":  ("m6",    [0, 3, 7, 9]),
    "add9":  ("add9",  [0, 4, 7, 2]),
    "5":     ("5",     [0, 7]),
}

# כינויים בכתיב רגיל -> איכות קנונית (הארוכים קודם)
SUFFIX_ALIASES = {
    "": "maj", "maj": "maj", "M": "maj",
    "m": "min", "min": "min", "-": "min",
    "7": "7", "dom7": "7",
    "maj7": "maj7", "M7": "maj7", "Δ": "maj7", "Δ7": "maj7", "ma7": "maj7",
    "m7": "min7", "min7": "min7", "-7": "min7",
    "9": "9", "maj9": "maj9", "M9": "maj9", "m9": "min9", "min9": "min9",
    "11": "11", "13": "13",
    "dim": "dim", "°": "dim", "o": "dim",
    "dim7": "dim7", "°7": "dim7", "o7": "dim7",
    "m7b5": "hdim7", "m7-5": "hdim7", "ø": "hdim7", "ø7": "hdim7", "hdim7": "hdim7",
    "aug": "aug", "+": "aug", "#5": "aug",
    "sus2": "sus2", "sus4": "sus4", "sus": "sus4",
    "7sus4": "7sus4", "7sus": "7sus4",
    "6": "6", "m6": "min6", "min6": "min6",
    "add9": "add9", "add2": "add9", "5": "5",
}

# תוויות Harte של lv-chordia -> איכות קנונית
HARTE_QUALITY = {
    "maj": "maj", "min": "min", "7": "7", "maj7": "maj7", "min7": "min7",
    "9": "9", "maj9": "maj9", "min9": "min9", "11": "11", "13": "13",
    "dim": "dim", "dim7": "dim7", "hdim7": "hdim7", "aug": "aug",
    "sus2": "sus2", "sus4": "sus4", "sus4(b7)": "7sus4", "maj6": "6", "min6": "min6",
    "5": "5", "1": "5",
}

HARTE_DEGREE = {
    "1": 0, "b2": 1, "2": 2, "#2": 3, "b3": 3, "3": 4, "4": 5, "#4": 6, "b5": 6,
    "5": 7, "#5": 8, "b6": 8, "6": 9, "bb7": 9, "b7": 10, "7": 11, "b9": 1, "9": 2,
    "#9": 3, "11": 5, "#11": 6, "b13": 8, "13": 9,
}

MINORISH = {"min", "min7", "min9", "min6", "dim", "dim7", "hdim7"}


@dataclass(frozen=True)
class Chord:
    root: Optional[int]          # None = N.C. (אין אקורד)
    quality: str = "maj"
    bass: Optional[int] = None

    @property
    def is_none(self) -> bool:
        return self.root is None

    def intervals(self) -> list[int]:
        return QUALITIES.get(self.quality, QUALITIES["maj"])[1]

    def pitch_classes(self) -> list[int]:
        if self.root is None:
            return []
        pcs = [(self.root + i) % 12 for i in self.intervals()]
        if self.bass is not None and self.bass not in pcs:
            pcs.append(self.bass)
        return pcs

    def transpose(self, semitones: int) -> "Chord":
        if self.root is None:
            return self
        return Chord((self.root + semitones) % 12, self.quality,
                     None if self.bass is None else (self.bass + semitones) % 12)

    def to_harte(self) -> str:
        if self.root is None:
            return "N"
        s = f"{SHARP_NAMES[self.root]}:{self.quality}"
        if self.bass is not None and self.bass != self.root:
            s += f"/{SHARP_NAMES[self.bass]}"
        return s


def _parse_note(s: str) -> tuple[int, int]:
    """מחזיר (pitch class, אורך שנצרך)."""
    pc = LETTER_PC[s[0].upper()]
    n = 1
    while n < len(s) and s[n] in "#b♯♭":
        pc += 1 if s[n] in "#♯" else -1
        n += 1
    return pc % 12, n


_NAME_RE = re.compile(r"^([A-Ga-g][#b♯♭]*)(.*?)(?:/([A-Ga-g][#b♯♭]*))?$")


def parse(label: str) -> Chord:
    """מפענח תווית Harte (C:min7/b7) או שם רגיל (Cm7/Bb). זורק ValueError אם לא מזוהה."""
    label = (label or "").strip()
    if label in ("", "N", "X", "N.C.", "NC", "N.C"):
        return Chord(None)

    label = _solfege_to_letters(label)
    if ":" in label or re.fullmatch(r"[A-G][#b]*(/[#b]*\d+)?", label):
        # Harte
        root_part, _, rest = label.partition(":")
        root, _ = _parse_note(root_part.split("/")[0])
        qual_part, _, bass_part = (rest or "maj").partition("/")
        if not rest and "/" in label:
            bass_part = label.split("/", 1)[1]
        quality = HARTE_QUALITY.get(qual_part or "maj")
        if quality is None:
            quality = _approx_harte(qual_part)
        bass = None
        if bass_part:
            if bass_part[0] in "ABCDEFG":
                bass, _ = _parse_note(bass_part)
            elif bass_part in HARTE_DEGREE:
                bass = (root + HARTE_DEGREE[bass_part]) % 12
        return Chord(root, quality, None if bass == root else bass)

    m = _NAME_RE.match(label)
    if not m:
        raise ValueError(f"שם אקורד לא מזוהה: {label}")
    root, _ = _parse_note(m.group(1))
    suffix = m.group(2).replace("♯", "#").replace("♭", "b").replace("(", "").replace(")", "")
    quality = SUFFIX_ALIASES.get(suffix)
    if quality is None:
        raise ValueError(f"סיומת אקורד לא מוכרת: {label}")
    bass = _parse_note(m.group(3))[0] if m.group(3) else None
    return Chord(root, quality, None if bass == root else bass)


_SOLFEGE_ROOTS = [("סול", "G"), ("דו", "C"), ("רה", "D"), ("מי", "E"), ("פה", "F"), ("לה", "A"), ("סי", "B"),
                  ("Sol", "G"), ("Do", "C"), ("Re", "D"), ("Mi", "E"), ("Fa", "F"), ("La", "A"), ("Si", "B")]


def _solfege_to_letters(label: str) -> str:
    """"לה m7", "סי♭/רה", "Sol7" -> "Am7", "Bb/D", "G7" — כדי שה-UI יוכל להחזיר שמות בכל כתיב."""
    parts = label.split("/")
    out = []
    for part in parts:
        for syl, letter in _SOLFEGE_ROOTS:
            if part.startswith(syl):
                part = letter + part[len(syl):].replace(" ", "").replace("-", "")
                break
        out.append(part)
    return "/".join(out)


def _approx_harte(q: str) -> str:
    """איכויות נדירות מהמילון המלא -> הקרובה ביותר."""
    if q.startswith("min") or q.startswith("(b3"):
        return "min7" if "7" in q else "min"
    if q.startswith("maj7") or q.startswith("maj9"):
        return "maj7"
    if q[:1].isdigit() and q[:1] in "79" or q.startswith("11") or q.startswith("13"):
        return "7"
    if q.startswith("dim"):
        return "dim"
    if q.startswith("aug") or "#5" in q:
        return "aug"
    if q.startswith("sus"):
        return "sus4"
    return "maj"


# ---------------------------------------------------------------- פישוט

def simplify(ch: Chord, level: str) -> Chord:
    """basic = מז'ור/מינור בלבד, standard = אקורדים נפוצים (ברירת מחדל), full = כמו שזוהה."""
    if ch.is_none or level == "full":
        return ch
    q = ch.quality
    if level == "basic":
        return Chord(ch.root, "min" if q in MINORISH else "maj", None)
    table = {"9": "7", "11": "7sus4", "13": "7", "maj9": "maj7", "min9": "min7", "add9": "maj"}
    return Chord(ch.root, table.get(q, q), ch.bass)


# ---------------------------------------------------------------- כתיב

FLAT_MAJOR_KEYS = {5, 10, 3, 8, 1}          # F Bb Eb Ab Db
FLAT_MINOR_KEYS = {2, 7, 0, 5, 10, 3}       # Dm Gm Cm Fm Bbm Ebm


def prefers_flats(key: Optional["Key"]) -> bool:
    if key is None:
        return False
    return key.tonic in (FLAT_MINOR_KEYS if key.minor else FLAT_MAJOR_KEYS)


MAJOR_SCALE = {0, 2, 4, 5, 7, 9, 11}
MINOR_SCALE = {0, 2, 3, 5, 7, 8, 10}


def flat_policy(key: Optional["Key"], accidentals: str = "auto"):
    """מחזיר פונקציה pc -> האם לכתוב במול. auto: תווי הסולם לפי סימני הסולם,
    תווים שאולים לפי תפקידם (bVII בדו מז'ור = Bb, V במינור = E עם G#)."""
    if accidentals in ("sharps", "flats"):
        return lambda pc: accidentals == "flats"
    if key is None:
        return lambda pc: False
    key_flats = prefers_flats(key)
    scale = MINOR_SCALE if key.minor else MAJOR_SCALE
    borrowed_flat = {1} if key.minor else {1, 3, 8, 10}

    def policy(pc: int) -> bool:
        rel = (pc - key.tonic) % 12
        if rel in scale:
            return key_flats
        return rel in borrowed_flat
    return policy


def note_name(pc: int, notation: str = "letters", flats=False) -> str:
    if callable(flats):
        flats = flats(pc % 12)
    table = {
        "letters": FLAT_NAMES if flats else SHARP_NAMES,
        "solfege_he": SOLFEGE_HE_FLAT if flats else SOLFEGE_HE,
        "solfege": SOLFEGE_FLAT if flats else SOLFEGE,
    }[notation]
    return table[pc % 12]


def format_chord(ch: Chord, notation: str = "letters", flats=False) -> str:
    """flats: bool, או פונקציה מ-flat_policy."""
    if ch.is_none:
        return "N.C."
    suffix = QUALITIES.get(ch.quality, ("", []))[0]
    # בסולפג' עברי רווח בין השורש לסיומת הלטינית ("לה m7"), אחרת הכיווניות מתבלבלת
    sep = " " if notation == "solfege_he" and suffix else ""
    s = note_name(ch.root, notation, flats) + sep + suffix
    if ch.bass is not None:
        s += "/" + note_name(ch.bass, notation, flats)
    return s


# ---------------------------------------------------------------- סולם

@dataclass(frozen=True)
class Key:
    tonic: int
    minor: bool

    def name(self, notation="letters", flats=None) -> str:
        if flats is None:
            flats = prefers_flats(self)
        return note_name(self.tonic, notation, flats) + ("m" if self.minor else "")

    def transpose(self, semitones: int) -> "Key":
        return Key((self.tonic + semitones) % 12, self.minor)


# פרופילי Krumhansl-Kessler
_KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def parse_key(s: str) -> Key:
    s = s.strip()
    minor = s.endswith("m") and not s.endswith("maj")
    pc, _ = _parse_note(s)
    return Key(pc, minor)


def _rank_keys(timeline: list[tuple[float, float, Chord]]) -> list[tuple[float, "Key"]]:
    """דירוג סולמות לפי פרופיל הצלילים (Krumhansl) + רמזים הרמוניים."""
    import numpy as np
    prof = np.zeros(12)
    played = [(s, e, ch) for s, e, ch in timeline if not ch.is_none and e > s]
    for start, end, ch in played:
        dur = end - start
        for i, pc in enumerate(ch.pitch_classes()):
            prof[pc] += dur * (1.5 if i == 0 else 1.0)      # שורש מקבל משקל יתר
    if prof.sum() == 0:
        return []
    dur_by, dom = {}, {}
    for s, e, ch in played:
        dur_by[(ch.root, ch.quality in MINORISH)] = dur_by.get((ch.root, ch.quality in MINORISH), 0.0) + e - s
        if ch.quality in ("7", "9", "13", "7sus4"):
            dom[(ch.root + 5) % 12] = dom.get((ch.root + 5) % 12, 0.0) + e - s
    total = sum(dur_by.values()) or 1.0
    first, last = played[0][2], played[-1][2]

    def bonus(k: Key) -> float:
        b = 0.0
        if last.root == k.tonic and (last.quality in MINORISH) == k.minor:
            b += 0.10                                       # שירים נגמרים על הטוניקה
        if first.root == k.tonic and (first.quality in MINORISH) == k.minor:
            b += 0.04
        b += 0.10 * min(1.0, dom.get(k.tonic, 0.0) / total * 4)      # V7 -> I
        b += 0.06 * min(1.0, dur_by.get((k.tonic, k.minor), 0.0) / total * 4)
        return b

    scores = []
    for minor, base in ((False, _KK_MAJOR), (True, _KK_MINOR)):
        for t in range(12):
            r = float(np.corrcoef(prof, np.roll(base, t))[0, 1])
            k = Key(t, minor)
            scores.append((r + bonus(k), k))
    scores.sort(key=lambda x: -x[0])
    return scores


def detect_key(timeline: list[tuple[float, float, Chord]], window: float = 60.0) -> tuple[Optional[Key], float]:
    """זיהוי סולם מתוך האקורדים. הביטחון יורד כשחלקי השיר לא מסכימים
    (מחרוזת או שיר עם מודולציה)."""
    scores = _rank_keys(timeline)
    if not scores:
        return None, 0.0
    best = scores[0]
    conf = max(0.0, min(1.0, (best[0] - scores[2][0]) * 5 + best[0] * 0.5))
    span = timeline[-1][1] - timeline[0][0] if timeline else 0.0
    if span > window * 1.5:
        agree = 0
        chunks = 0
        t = timeline[0][0]
        while t < timeline[-1][1]:
            part = [x for x in timeline if x[0] >= t and x[1] <= t + window]
            t += window
            sub = _rank_keys(part)
            if not sub:
                continue
            chunks += 1
            agree += sub[0][1] == best[1]
        if chunks:
            conf *= 0.3 + 0.7 * agree / chunks
    return best[1], round(float(conf), 2)


# ---------------------------------------------------------------- גיטרה

STRINGS_PC = [4, 9, 2, 7, 11, 4]   # E A D G B e
X = None

OPEN_SHAPES = {
    "C": [X, 3, 2, 0, 1, 0], "A": [X, 0, 2, 2, 2, 0], "G": [3, 2, 0, 0, 0, 3],
    "E": [0, 2, 2, 1, 0, 0], "D": [X, X, 0, 2, 3, 2],
    "Am": [X, 0, 2, 2, 1, 0], "Em": [0, 2, 2, 0, 0, 0], "Dm": [X, X, 0, 2, 3, 1],
    "C7": [X, 3, 2, 3, 1, 0], "A7": [X, 0, 2, 0, 2, 0], "G7": [3, 2, 0, 0, 0, 1],
    "E7": [0, 2, 0, 1, 0, 0], "D7": [X, X, 0, 2, 1, 2], "B7": [X, 2, 1, 2, 0, 2],
    "Am7": [X, 0, 2, 0, 1, 0], "Em7": [0, 2, 0, 0, 0, 0], "Dm7": [X, X, 0, 2, 1, 1],
    "Cmaj7": [X, 3, 2, 0, 0, 0], "Fmaj7": [X, X, 3, 2, 1, 0], "Dmaj7": [X, X, 0, 2, 2, 2],
    "Amaj7": [X, 0, 2, 1, 2, 0], "Emaj7": [0, 2, 1, 1, 0, 0], "Gmaj7": [3, 2, 0, 0, 0, 2],
    "Asus2": [X, 0, 2, 2, 0, 0], "Asus4": [X, 0, 2, 2, 3, 0], "Dsus2": [X, X, 0, 2, 3, 0],
    "Dsus4": [X, X, 0, 2, 3, 3], "Esus4": [0, 2, 2, 2, 0, 0], "Csus2": [X, 3, 0, 0, 3, 3],
    "Csus4": [X, 3, 3, 0, 1, 1], "Gsus4": [3, 3, 0, 0, 1, 3],
    "A7sus4": [X, 0, 2, 0, 3, 0], "D7sus4": [X, X, 0, 2, 1, 3], "E7sus4": [0, 2, 0, 2, 0, 0],
    "Cadd9": [X, 3, 2, 0, 3, 0], "Gadd9": [3, X, 0, 2, 0, 3],
    "A5": [X, 0, 2, 2, X, X], "E5": [0, 2, 2, X, X, X], "D5": [X, X, 0, 2, 3, X],
    "Am6": [X, 0, 2, 2, 1, 2], "Em6": [0, 2, 2, 0, 2, 0], "A6": [X, 0, 2, 2, 2, 2],
    "E6": [0, 2, 2, 1, 2, 0], "Caug": [X, 3, 2, 1, 1, 0], "Bdim": [X, 2, 3, 4, 3, X],
}
EASY_SHAPES = set(OPEN_SHAPES)

# תבניות נידות: היסט מהסריג של השורש (None = מושתק)
E_SHAPES = {   # שורש על מיתר 6
    "maj": [0, 2, 2, 1, 0, 0], "min": [0, 2, 2, 0, 0, 0], "7": [0, 2, 0, 1, 0, 0],
    "min7": [0, 2, 0, 0, 0, 0], "maj7": [0, X, 1, 1, 0, X], "sus4": [0, 2, 2, 2, 0, 0],
    "7sus4": [0, 2, 0, 2, 0, 0], "13": [0, X, 0, 1, 2, X], "5": [0, 2, 2, X, X, X],
    "6": [0, X, -1, 1, 0, X], "min6": [0, X, -1, 0, 0, X],
}
A_SHAPES = {   # שורש על מיתר 5
    "maj": [X, 0, 2, 2, 2, 0], "min": [X, 0, 2, 2, 1, 0], "7": [X, 0, 2, 0, 2, 0],
    "min7": [X, 0, 2, 0, 1, 0], "maj7": [X, 0, 2, 1, 2, 0], "sus2": [X, 0, 2, 2, 0, 0],
    "sus4": [X, 0, 2, 2, 3, 0], "7sus4": [X, 0, 2, 0, 3, 0], "hdim7": [X, 0, 1, 0, 1, X],
    "dim7": [X, 0, 1, -1, 1, X], "dim": [X, 0, 1, 2, 1, X], "aug": [X, 0, -1, -2, -2, X],
    "9": [X, 0, -1, 0, 0, 0], "min9": [X, 0, -2, 0, 0, 0], "maj9": [X, 0, -1, 1, 0, X],
    "add9": [X, 0, -1, -3, 0, X], "5": [X, 0, 2, 2, X, X], "6": [X, 0, 2, 2, 2, 2],
    "min6": [X, 0, 2, -1, 1, X],
}


def _shape_name(ch: Chord) -> str:
    return SHARP_NAMES[ch.root] + QUALITIES[ch.quality][0]


def _with_bass(frets: list, bass: int) -> Optional[list]:
    played = [f for f in frets if f is not None and f > 0]
    lo, hi = (min(played), max(played)) if played else (0, 3)
    best = None
    for s in (0, 1):
        for f in ((bass - STRINGS_PC[s]) % 12, (bass - STRINGS_PC[s]) % 12 + 12):
            if f > 15:
                continue
            # כמה הבס מותח את היד מחוץ לטווח האקורד (מיתר פתוח = 0)
            stretch = 0 if f == 0 else max(0, lo - f, f - hi)
            if f and stretch > 2:
                continue
            score = stretch + s * 0.5
            if best is None or score < best[0]:
                best = (score, s, f)
    if best is None:
        return None
    _, s, f = best
    out = list(frets)
    out[s] = f
    for lower in range(s):
        out[lower] = None
    return out


def guitar_shapes(ch: Chord, limit: int = 3) -> list[dict]:
    """אצבועי גיטרה. frets: 6 ערכים ממיתר E נמוך עד e גבוה, null = לא מנגנים, 0 = פתוח."""
    if ch.is_none:
        return []
    base = Chord(ch.root, ch.quality)
    cands = []
    name = _shape_name(base)
    if name in OPEN_SHAPES:
        cands.append(("open", list(OPEN_SHAPES[name])))
    for kind, table, string in (("E", E_SHAPES, 0), ("A", A_SHAPES, 1)):
        if ch.quality in table:
            r = (ch.root - STRINGS_PC[string]) % 12
            if r == 0:
                r = 12 if name in OPEN_SHAPES else 0
            offs = table[ch.quality]
            if r + min(o for o in offs if o is not None) < 0:
                r += 12
            frets = [None if o is None else r + o for o in offs]
            cands.append((f"{kind}-shape", frets))
    out = []
    for kind, frets in cands:
        if ch.bass is not None:
            frets = _with_bass(frets, ch.bass)
            if frets is None:
                continue
        played = [f for f in frets if f is not None and f > 0]
        base_fret = min(played) if played and max(played) > 4 else 1
        barre = None
        if kind != "open" and played:
            low = min(played)
            if sum(1 for f in frets if f == low) >= 2:
                barre = low
        out.append({"frets": frets, "base_fret": base_fret, "barre": barre, "type": kind})
    out.sort(key=lambda s: (s["type"] != "open", min([f for f in s["frets"] if f] or [0])))
    seen, uniq = set(), []
    for s in out:
        k = tuple(s["frets"])
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return uniq[:limit]


def piano_notes(ch: Chord) -> list[dict]:
    """תווים לפסנתר (MIDI סביב C4), הבס אוקטבה מתחת."""
    if ch.is_none:
        return []
    notes = []
    if ch.bass is not None:
        notes.append({"midi": 48 + ch.bass, "pc": ch.bass, "role": "bass"})
    prev = 59 + 0
    for i, iv in enumerate(QUALITIES[ch.quality][1]):
        pc = (ch.root + iv) % 12
        m = 60 + pc if i == 0 else prev + ((pc - prev) % 12 or 12)
        if i == 0 and m > 66:
            m -= 12
        notes.append({"midi": m, "pc": pc, "role": "root" if i == 0 else "tone"})
        prev = m
    return notes


def is_easy_guitar(ch: Chord) -> bool:
    return ch.is_none or _shape_name(Chord(ch.root, ch.quality)) in EASY_SHAPES


def suggest_capo(timeline: list[tuple[float, float, Chord]], max_capo: int = 7) -> list[dict]:
    """לכל קאפו 0..7: כמה מזמן השיר מנוגן באקורדים קשים (ברה וכו'). מחזיר את הטובים ראשונים."""
    total = sum(e - s for s, e, c in timeline if not c.is_none) or 1.0
    res = []
    for capo in range(max_capo + 1):
        hard = sum(e - s for s, e, c in timeline if not is_easy_guitar(c.transpose(-capo)))
        uniq_hard = {format_chord(c.transpose(-capo)) for s, e, c in timeline
                     if not is_easy_guitar(c.transpose(-capo))}
        res.append({"capo": capo, "hard_ratio": round(hard / total, 3),
                    "hard_chords": sorted(uniq_hard), "score": hard / total + capo * 0.015})
    res.sort(key=lambda r: r["score"])
    for r in res:
        del r["score"]
    return res
