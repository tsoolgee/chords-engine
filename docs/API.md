# API של המנוע

השרת מאזין ל-`http://127.0.0.1:8765`, ורק למחשב המקומי. אפשר לשנות את הפורט עם `--port`.
כל התשובות הן JSON ב-UTF-8. שגיאה מוחזרת כך: `{"error": "הודעה בעברית"}`, עם סטטוס 400/404/500.
CORS פתוח, כך שגם ממשק שרץ בדפדפן או ב-WebView2 יכול לפנות לשרת.

הפעלה: `python -m chords_engine serve`. הממשק יכול להפעיל את השרת בעצמו כתהליך רקע ולבדוק שהוא עלה עם `GET /api/health`.

## נתיבים

| שיטה | נתיב | תיאור |
|---|---|---|
| GET | `/api/health` | `{ok, version}` |
| GET | `/api/config` | ברירות מחדל, מודלים מותקנים, זמינות demucs/VAD |
| POST | `/api/analyze` | `{path, options}` → עבודה (202) |
| POST | `/api/upload` | גוף = הקובץ עצמו, כותרת `X-Filename`. מחזיר `{path}`. לממשק שאין לו גישה לנתיב אמיתי |
| GET | `/api/jobs` | כל העבודות |
| GET | `/api/jobs/{id}` | מצב עבודה |
| GET | `/api/jobs/{id}/events` | SSE: הודעה בכל שינוי, נסגר כשהעבודה מסתיימת |
| POST | `/api/jobs/{id}/cancel` | ביטול |
| GET | `/api/songs` | ספרייה (תקציר) |
| GET | `/api/songs/{id}?transpose=&capo=&simplify=&notation=&accidentals=&show_carried=&include_shapes=` | **תצוגת שיר** |
| PUT | `/api/songs/{id}` | שמירת עריכות → מחזיר תצוגה מעודכנת |
| POST | `/api/songs/{id}/lyrics` | `{text, view}`: יישור מילים נכונות ובניית השורות מחדש. `text` ריק מחזיר לתמלול |
| POST | `/api/songs/{id}/reset` | חזרה לתוצאת הניתוח המקורית |
| POST | `/api/songs/{id}/reanalyze` | `{options}`: ניתוח מחדש של אותו קובץ → עבודה |
| DELETE | `/api/songs/{id}` | מחיקה מהספרייה (קובץ השמע עצמו לא נמחק) |
| GET | `/api/songs/{id}/raw` | המסמך השמור כמו שהוא, בסולם המקור |
| GET | `/api/songs/{id}/export?format=txt\|chordpro\|lrc\|json&transpose=...` | קובץ להורדה |
| GET | `/api/songs/{id}/audio` | קובץ השמע המקורי (תומך `Range`) |
| GET | `/api/chord?name=Am7/G&notation=&accidentals=` | פענוח שם + אצבועים + תווים |
| GET | `/api/chords/vocabulary?notation=` | שורשים וסוגי אקורדים לבורר |

## אפשרויות ניתוח (`options`)

| שדה | ברירת מחדל | |
|---|---|---|
| `language` | `"he"` | שפת השירה (אפשר גם `"auto"`) |
| `whisper_model` | `ggml-ivrit-large-v3-turbo-q5_0.bin` | קובץ מתוך `vendor/models` |
| `accurate_timing` | `false` | DTW: תזמון מילים מדויק יותר, בערך +40% זמן |
| `threads` | מספר הליבות | |
| `vad` | `false` | ניסיוני. מהיר פי 2, אבל בבדיקה איבד את השורה הראשונה והזיז זמנים |
| `separate_vocals` | `false` | demucs, אם מותקן |
| `chord_vocabulary` | `"submission"` | `ismir2017` (מז'ור/מינור) / `submission` (~170) / `full` |
| `min_chord_duration` | `0.35` | אקורד קצר מזה (בשניות) מתמזג לשכנו |
| `snap_to_beats` | `true` | יישור החלפות אקורד לפעמה הקרובה |
| `prompt` | `""` | רמז ל-whisper |
| `lyrics_text` | `""` | מילים ידועות (שורה = שורה, שורה ריקה = בית) |
| `skip_lyrics` | `false` | אקורדים בלבד, בערך פי 5 מהר יותר |
| `force` | `false` | לנתח מחדש גם אם הקובץ כבר בספרייה |

## עבודה (Job)

```json
{
  "id": "0ea865615fcc", "status": "running",          // queued | running | done | error | cancelled
  "stage": "lyrics", "stage_label": "מתמלל מילים",
  "stage_progress": 0.42, "progress": 0.61,
  "stages": [{"id": "decode", "label": "מפענח את קובץ השמע"}, {"id": "chords", "label": "מזהה אקורדים"}, "..."],
  "song_id": null, "error": null, "created": 1790096419.5, "finished": null
}
```

האזנה לעדכונים חיים ב-JS:
```js
const es = new EventSource(`http://127.0.0.1:8765/api/jobs/${id}/events`);
es.onmessage = e => { const job = JSON.parse(e.data); render(job); if (job.status !== "running" && job.status !== "queued") es.close(); };
```

## תצוגת שיר (`GET /api/songs/{id}`)

```jsonc
{
  "id": "63500297281d65fd",
  "meta": {
    "title": "שם השיר", "artist": "", "duration": 213.4, "tempo": 129.2, "time_signature": "4/4",
    "key": "Eb",            // הסולם שנשמע אחרי טרנספוזיציה
    "key_original": "C",    // הסולם שזוהה
    "shape_key": "C",       // הסולם שבו מנגנים (אחרי קאפו)
    "key_confidence": 0.8, "language": "he"
  },
  "view": {"transpose": 3, "capo": 3, "simplify": "standard", "notation": "letters", "accidentals": "auto", "show_carried": true, "include_shapes": true},
  "sections": [{"id": "S1", "kind": "intro", "number": 0, "start": 0, "end": 12.1},
               {"id": "S2", "kind": "verse", "number": 1, "start": 12.1, "end": 40.3}],
  "lines": [
    {"id": "L1", "type": "instrumental", "role": "intro", "section": "S1", "start": 0, "end": 12.1,
     "chords": [{"label": "C:maj", "name": "C", "time": 0.5, "duration": 3.7, "beats": 8, "carried": false}]},
    {"id": "L2", "type": "lyric", "section": "S2", "start": 12.1, "end": 15.2,
     "text": "הגמרא כבר אומרת שחברך",
     "words": [{"text": "הגמרא", "start": 12.1, "end": 12.6, "p": 0.99, "char": 0}, "..."],
     "chords": [{"char": 0, "label": "G:maj", "name": "G", "time": 12.1, "carried": true},
                {"char": 16, "label": "A:min", "name": "Am", "time": 14.0, "carried": false}],
     "stanza_break": false}
  ],
  "timeline": [{"start": 0.5, "end": 4.2, "label": "C:maj", "name": "C"}, "..."],   // לנגן
  "beats": [0.46, 0.93, "..."],
  "chords_used": [{"name": "C", "label": "C:maj",
                   "guitar": [{"frets": [null, 3, 2, 0, 1, 0], "base_fret": 1, "barre": null, "type": "open"}],
                   "piano": [{"midi": 60, "pc": 0, "role": "root"}, {"midi": 64, "pc": 4, "role": "tone"}]}],
  "capo_suggestions": [{"capo": 3, "hard_ratio": 0.117, "hard_chords": ["F"]}, "..."],
  "lyrics_source": "transcript",     // transcript | user | none
  "source": {"path": "C:\\...\\song.mp3", "name": "song.mp3", "size": 1411244}
}
```

- `name` הוא מה שמציגים. הוא כבר כולל טרנספוזיציה, קאפו, פישוט וכתיב.
- `label` הוא האקורד **בסולם המקור**, בכתיב Harte (`A:min7/G`). הוא משמש לזיהוי ולא לתצוגה.
- `char` הוא אינדקס בתוך `text`, שסופר מתחילת השורה, כלומר מימין. הממשק מודד את רוחב
  `text.slice(0, char)` וממקם את האקורד כך שהקצה הימני שלו יושב מעל האות.
- `time` הוא זמן בשניות, ומשמש לסנכרון עם הנגן.

## עריכה (`PUT /api/songs/{id}`)

שולחים את **כל** רשימת `lines` (לא רק שורות שהשתנו), ואיתה את ה-`view` שבו המשתמש ערך:

```json
{
  "view": {"transpose": 2, "capo": 0},
  "meta": {"title": "שם מתוקן", "artist": "מבצע"},
  "lines": [ { "id": "L2", "type": "lyric", "text": "הטקסט המתוקן",
               "chords": [{"char": 0, "name": "Em7"}, {"char": 9, "name": "A"}] } ]
}
```

- אקורד עם `name` מתפרש **בסולם של `view`**, ואפשר לכתוב אותו בכל כתיב (`Em7`, `E:min7`, `מי m7`).
  המנוע מחזיר אותו לסולם המקור בעצמו. אקורד בלי `name` צריך `label` בסולם המקור.
- אם טקסט השורה השתנה, המנוע מחשב מחדש את מיקומי המילים. אם מספר המילים לא השתנה, הזמנים נשמרים.
- `sections` אופציונלי. בלעדיו החלוקה לבתים מחושבת מחדש.
- התשובה היא תצוגה מעודכנת (כמו GET). אקורד לא חוקי מחזיר 400 עם הודעה.

## ייצוא

`export?format=txt` מחזיר אקורדים מעל מילים, עם סימני כיוון (RLM), כך שהתוצאה מוצגת נכון
בפנקס רשימות ובוואטסאפ. לתצוגה מדויקת צריך גופן ברוחב קבוע.
`chordpro` מחזיר `[Am]` בתוך השורה, ועובד בכל אפליקציית ChordPro.
