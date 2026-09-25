# PP-OCRv6 constrained baseline: real golden-fixture accuracy

## Before/after on identical scored crops

| Field | Scored | canonical_exact original | constrained | change | char_similarity original | constrained | change |
|---|---:|---:|---:|---:|---:|---:|---:|
| date | 71 | 7.0% | 7.0% | +0.0 pp | 0.211 | 0.214 | +0.003 |
| start_time | 71 | 22.5% | 22.5% | +0.0 pp | 0.507 | 0.537 | +0.029 |
| close_time | 71 | 15.5% | 15.5% | +0.0 pp | 0.482 | 0.490 | +0.008 |

Mean OCR confidence also changed: date 0.919 → 0.906; start_time 0.833 → 0.709; close_time 0.804 → 0.775. Confidence affects review flagging in the sheet pipeline.

`char_similarity` compares the raw OCR text with normalized ground truth (for example, a handwritten date with an ISO date), so it is diagnostic rather than a date parse score.

## Decoder method and limitation

The PP-OCRv6 medium model keeps its trained character dictionary. PaddleOCR 3.x binds output indices to that dictionary; replacing it at inference would mislabel predictions. This run masks all CTC classes except blank, digits, and `/:-.|` before PaddleX's original CTC decoder chooses classes. The mask applies only to date and clock fields; no text correction is performed after recognition. Both `|`/`/` and `1` remain allowed, so a character-only mask cannot force a separator where the model favors `1`. Visual inspection of the anonymized crops shows near-vertical separator strokes; the JSON alone does not establish a literal slash substitution.

The raw date readings `718126` (sheet_001 row 6), `1618126` (sheet_003 row 0), `0218126` (sheet_004 row 1), and `118126` (sheet_005 row 0) remained unchanged by the mask.

Implementation basis: [PP-OCRv6 model configuration](https://github.com/PaddlePaddle/PaddleOCR/blob/main/configs/rec/PP-OCRv6/PP-OCRv6_medium_rec.yml), [PaddleOCR maintainer guidance](https://github.com/PaddlePaddle/PaddleOCR/discussions/17635), and [PaddleX 3.7 CTC decoder](https://github.com/PaddlePaddle/PaddleX/blob/release/3.7/paddlex/inference/models/text_recognition/processors.py).

Date, start_time, and close_time use a CTC character mask (digits and separators); all other fields use the original decoder. The same five fixtures, crops, buckets, and scoring rules as ppocrv6-baseline are used. This is a measurement, not a pass/fail gate. Numbers are reported as produced, with no filtering or tuning to improve them -- see Task C1 in IMPLEMENTATION_PLAN.md.

Canonicalization rules (fixed before this baseline was first run; see
tests/support/baseline_scoring.py for the implementation):

- All fields: strip surrounding whitespace, collapse internal whitespace, uppercase.
- `date`: parsed against `%Y-%m-%d`, `%d/%m/%Y`, `%d/%m/%y`, `%d-%m-%Y`, `%d-%m-%y`,
  `%d.%m.%Y`, `%d.%m.%y`, `%d|%m|%Y`, `%d|%m|%y` (first match wins); unparseable => no match.
- `start_time` / `close_time`: parsed against `%H:%M`, `%I:%M %p`, `%I:%M%p`, `%I.%M %p`;
  unparseable => no match.
- `start_km` / `close_km` / `total_km`: non-digit characters stripped, compared as integers.
- `total_time`: bare `12` => `12H` (a 12-hour duty, the form's own convention);
  `0`/`0H` => `0H`; `1D`/`1DAY`/`DAY` => `1D`; anything else => no match.
- `toll` / `parking`: a blank cell => `0` (the form's convention: blank means nothing paid);
  otherwise non-digit characters are stripped.

No rule was added or changed after seeing a result. `raw_exact` (verbatim string equality,
no transformation at all) is always the headline number -- `canonical_exact` is a second,
clearly-labelled number alongside it, not a replacement for it.

### All sheets combined

| Field | Scored | raw_exact | canonical_exact | mean char_similarity | mean confidence |
|---|---|---|---|---|---|
| date | 71 | 0.0% | 7.0% | 0.214 | 0.906 |
| start_time | 71 | 5.6% | 22.5% | 0.537 | 0.709 |
| start_km | 71 | 57.7% | 60.6% | 0.876 | 0.916 |
| close_time | 71 | 9.9% | 15.5% | 0.490 | 0.775 |
| close_km | 71 | 54.9% | 62.0% | 0.850 | 0.904 |
| total_km | 71 | 73.2% | 76.1% | 0.856 | 0.939 |
| total_time | 71 | 0.0% | 49.3% | 0.373 | 0.883 |
| toll | 71 | 0.0% | 76.1% | 0.093 | 0.331 |
| parking | 71 | 0.0% | 76.1% | 0.093 | 0.331 |
| journey_details | 55 | 7.3% | 7.3% | 0.592 | 0.757 |

### Excluded from scoring

- **scored**: 694 field crops
- **redacted**: 71 field crops -- guest_name crop is a black redaction box; OCR is never run on it
- **no_ground_truth**: 16 field crops -- ground truth is empty -- illegible to the human transcriber

### No usable ground truth -- not scored, OCR output shown for inspection

These rows are excluded from every accuracy number above. Reported here so the raw model output on genuinely illegible source material stays visible rather than hidden. This is a measurement, not a pass/fail check -- a bad reading here is expected, not a bug.

| Sheet | Row | Field | OCR text (verbatim) | OCR confidence |
|---|---|---|---|---|
| sheet_004 | 10 | journey_details | (nothing recognized) | 0.000 |
| sheet_005 | 0 | journey_details | G→SOZePON p-h toun | 0.647 |
| sheet_005 | 1 | journey_details | cl,be fo v2=4 1ztrzcpn | 0.602 |
| sheet_005 | 2 | journey_details | topn 128912 | 0.676 |
| sheet_005 | 3 | journey_details | GHTOVIN33Y tokmL18toGH | 0.776 |
| sheet_005 | 4 | journey_details | GHtopssto kml-1atoees | 0.808 |
| sheet_005 | 5 | journey_details | ci17 | 0.689 |
| sheet_005 | 6 | journey_details | GHARL-8十 GH- | 0.667 |
| sheet_005 | 7 | journey_details | GHStanding | 0.877 |
| sheet_005 | 8 | journey_details | Gt+0ss+ PSS+b1l | 0.680 |
| sheet_005 | 9 | journey_details | au+15+ D42Tcn | 0.507 |
| sheet_005 | 10 | journey_details | grruinn SSS+Rutun | 0.421 |
| sheet_005 | 11 | journey_details | (nt-112+ 12 F10s + 205 | 0.748 |
| sheet_005 | 12 | journey_details | art P.ht he 112+n2+2 | 0.716 |
| sheet_005 | 13 | journey_details | vutzeper 122+299+ 2 | 0.817 |
| sheet_005 | 14 | journey_details | G」299178 10S + 12A + | 0.773 |

### Run environment

- Model: PP-OCRv6 (medium tier)
- paddleocr: 3.7.0
- paddlepaddle: 3.3.1
- Device: cpu
- Total wall-clock time: 341.1s

## Per-sheet breakdown

### sheet_001

| Field | Scored | raw_exact | canonical_exact | mean char_similarity | mean confidence |
|---|---|---|---|---|---|
| date | 15 | 0.0% | 33.3% | 0.147 | 0.928 |
| start_time | 15 | 0.0% | 0.0% | 0.363 | 0.404 |
| start_km | 15 | 40.0% | 40.0% | 0.827 | 0.924 |
| close_time | 15 | 0.0% | 6.7% | 0.307 | 0.589 |
| close_km | 15 | 66.7% | 80.0% | 0.909 | 0.884 |
| total_km | 15 | 86.7% | 86.7% | 0.911 | 0.976 |
| total_time | 15 | 0.0% | 53.3% | 0.376 | 0.799 |
| toll | 15 | 0.0% | 93.3% | 0.000 | 0.392 |
| parking | 15 | 0.0% | 93.3% | 0.000 | 0.392 |
| journey_details | 15 | 0.0% | 0.0% | 0.655 | 0.757 |

### sheet_002

| Field | Scored | raw_exact | canonical_exact | mean char_similarity | mean confidence |
|---|---|---|---|---|---|
| date | 15 | 0.0% | 0.0% | 0.247 | 0.881 |
| start_time | 15 | 0.0% | 6.7% | 0.533 | 0.878 |
| start_km | 15 | 53.3% | 66.7% | 0.857 | 0.891 |
| close_time | 15 | 0.0% | 6.7% | 0.507 | 0.898 |
| close_km | 15 | 46.7% | 46.7% | 0.751 | 0.934 |
| total_km | 15 | 66.7% | 73.3% | 0.851 | 0.932 |
| total_time | 15 | 0.0% | 0.0% | 0.000 | 0.943 |
| toll | 15 | 0.0% | 93.3% | 0.000 | 0.056 |
| parking | 15 | 0.0% | 93.3% | 0.000 | 0.056 |
| journey_details | 15 | 20.0% | 20.0% | 0.595 | 0.741 |

### sheet_003

| Field | Scored | raw_exact | canonical_exact | mean char_similarity | mean confidence |
|---|---|---|---|---|---|
| date | 15 | 0.0% | 0.0% | 0.267 | 0.952 |
| start_time | 15 | 0.0% | 40.0% | 0.604 | 0.819 |
| start_km | 15 | 73.3% | 73.3% | 0.944 | 0.965 |
| close_time | 15 | 0.0% | 13.3% | 0.489 | 0.833 |
| close_km | 15 | 60.0% | 80.0% | 0.920 | 0.883 |
| total_km | 15 | 93.3% | 93.3% | 0.933 | 0.896 |
| total_time | 15 | 0.0% | 40.0% | 0.334 | 0.778 |
| toll | 15 | 0.0% | 86.7% | 0.000 | 0.268 |
| parking | 15 | 0.0% | 86.7% | 0.000 | 0.268 |
| journey_details | 15 | 0.0% | 0.0% | 0.513 | 0.721 |

### sheet_004

| Field | Scored | raw_exact | canonical_exact | mean char_similarity | mean confidence |
|---|---|---|---|---|---|
| date | 11 | 0.0% | 0.0% | 0.245 | 0.813 |
| start_time | 11 | 0.0% | 27.3% | 0.627 | 0.792 |
| start_km | 11 | 81.8% | 81.8% | 0.945 | 0.943 |
| close_time | 11 | 45.5% | 45.5% | 0.800 | 0.941 |
| close_km | 11 | 90.9% | 90.9% | 0.982 | 0.979 |
| total_km | 11 | 90.9% | 100.0% | 0.955 | 0.977 |
| total_time | 11 | 0.0% | 90.9% | 0.652 | 0.984 |
| toll | 11 | 0.0% | 100.0% | 0.000 | 0.000 |
| parking | 11 | 0.0% | 100.0% | 0.000 | 0.000 |
| journey_details | 10 | 10.0% | 10.0% | 0.609 | 0.834 |

### sheet_005

| Field | Scored | raw_exact | canonical_exact | mean char_similarity | mean confidence |
|---|---|---|---|---|---|
| date | 15 | 0.0% | 0.0% | 0.173 | 0.930 |
| start_time | 15 | 26.7% | 40.0% | 0.579 | 0.675 |
| start_km | 15 | 46.7% | 46.7% | 0.823 | 0.863 |
| close_time | 15 | 13.3% | 13.3% | 0.432 | 0.658 |
| close_km | 15 | 20.0% | 20.0% | 0.722 | 0.857 |
| total_km | 15 | 33.3% | 33.3% | 0.657 | 0.924 |
| total_time | 15 | 0.0% | 73.3% | 0.578 | 0.939 |
| toll | 15 | 0.0% | 13.3% | 0.439 | 0.849 |
| parking | 15 | 0.0% | 13.3% | 0.439 | 0.849 |
| journey_details | 0 | -- | -- | -- | -- |
