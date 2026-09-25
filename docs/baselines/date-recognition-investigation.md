# Date/time separator investigation: five real fixtures

## Outcome

Each line below covers the same 71 scored crops per field in the locked [PP-OCRv6
baseline](ppocrv6-baseline.md). `canonical_exact`, `char_similarity`, and mean
OCR confidence use the unchanged `tests/support/baseline_scoring.py` definitions.
All image runs use the same five anonymized sheet images, B1 preprocessing,
grid detection, and cell cropping as the original baseline. The 213 affected
date/time crops were rerun for each image intervention; the other 568 original
records were copied verbatim for the in-memory 781-record comparison. Each
JSON report publishes its 213 affected records, with the unaffected records
available in the original baseline. Recovery starts
from the original baseline's raw OCR results and reruns 71 DS.No crops; its
effective-value scores are explicitly separate from OCR scores.
An independent default-parameter [control run](date-recognition-control.json)
reproduced all 213 original date/time OCR strings, confidence values, and
scores exactly, ruling out baseline drift in this Docker environment.

| Approach | Date exact | Date similarity | Date confidence | Start exact | Start similarity | Start confidence | Close exact | Close similarity | Close confidence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Original PP-OCRv6 | 5/71 (7.0%) | 0.2113 | 0.9190 | 16/71 (22.5%) | 0.5071 | 0.8333 | 11/71 (15.5%) | 0.4825 | 0.8043 |
| Lower detector thresholds | 5/71 (7.0%) | 0.2127 | 0.9247 | 22/71 (31.0%) | 0.5354 | 0.8577 | 13/71 (18.3%) | 0.5238 | 0.8761 |
| Crop-local CLAHE | 5/71 (7.0%) | 0.2113 | 0.9204 | 18/71 (25.4%) | 0.5194 | 0.8587 | 11/71 (15.5%) | 0.4827 | 0.8039 |
| Bounded date reconstruction (effective value) | 6/71 (8.5%) | 0.2239 | 0.9190 raw OCR | 16/71 (22.5%) | 0.5071 | 0.8333 | 11/71 (15.5%) | 0.4825 | 0.8043 |
| Proposed field routing (lower thresholds for times only) | 5/71 (7.0%) | 0.2113 | 0.9190 | 22/71 (31.0%) | 0.5354 | 0.8577 | 13/71 (18.3%) | 0.5238 | 0.8761 |

The date gap remains unresolved by either image intervention. Lower detection
thresholds improved times without a mean-confidence regression, but one
previously correct date became wrong while one wrong date became correct.
CLAHE brought no date gain and slightly reduced close-time confidence. The
reconstruction is accurate for one field value here, but has no valid basis on
the other four sheets. It is a provisional inference, not an OCR read.

The production change routes `start_time` and `close_time` through the same
PP-OCRv6 predictor with the lower detection thresholds passed to `predict()`;
it keeps `date` and every other field on the original settings. Existing
generic `Recognizer` implementations keep their interface. The full
[field-routed report](date-recognition-field_routed.json) reran all 213 affected
crops and reproduced **every** time text/confidence from the detector spike
and **every** date text/confidence from the original control, record for record.

## Failure localization and research

The original date baseline contains `218/26` for 2026-08-02, `618/26` for
2026-08-06, and `718126` for 2026-08-07 on sheet_001; `1618126` for
2026-08-16 on sheet_003 and `0218126` for 2026-08-02 on sheet_004. These
are raw strings, not reconstructed values. Some separators are read as `1`;
others disappear or coexist with other digit mistakes.

The PP-OCRv6 text detector locates text **regions**, not individual slash
strokes. On four date failures inspected directly, it produced one region
spanning the date text; the downstream recognized strings were still wrong.
PaddleOCR documents `text_det_thresh` as the threshold on pixel probabilities
used to form text regions and `text_det_box_thresh` as the region acceptance
threshold (defaults 0.3 and 0.6). Lowering them can change the crop passed to
recognition, but cannot require the recognizer to emit a slash. [PaddleOCR OCR
pipeline reference](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md).

Handwriting enhancement work addresses thin, discontinuous strokes with
directional morphology, while document enhancement research uses local
contrast methods such as CLAHE. Neither demonstrates that CLAHE will help
these particular crops, so it was measured here. [Directional handwriting
morphology](https://doi.org/10.1016/j.ins.2020.11.019), [document-image
binarization with CLAHE](https://arxiv.org/abs/1901.09425).

Date-specific research also describes direct prediction of day, month, and
year components, avoiding separator transcription altogether. That is a
different future model experiment, not a measured result in this report.
[DARE date recognition system](https://link.springer.com/article/10.1007/s10032-026-00587-5).
The [TrOCR small handwritten model](https://huggingface.co/microsoft/trocr-small-handwritten)
is an image-encoder/text-decoder model trained for single handwritten text
lines. It is a relevant architectural comparison, but it was **not run** on
these five fixtures: the current pinned Docker image has neither PyTorch nor
Transformers, and TrOCR's generated-token probabilities would not be directly
comparable to PaddleOCR's reported line confidence. It needs a separate,
pinned model environment and a defined confidence protocol before it can be
judged under the same gate.

## Three measured approaches

1. **Detector sensitivity.** PP-OCRv6 medium detection and recognition,
   `text_det_thresh=0.1` and `text_det_box_thresh=0.3`, with all other settings
   and crop pixels unchanged. It changed 15 date, 21 start-time, and 28
   close-time OCR strings. Date was one correction (`718126` to `7/8/26`) and
   one regression (`8/8/26` to `818/26`). Start time had six corrections and
   no losses; close time had three corrections and one loss. The aggregate
   time gains are real within these five fixtures; individual errors remain.
   Mean confidence did fall on some individual sheets despite rising overall:
   start_time on sheet_001 (0.711 to 0.697), close_time on sheet_002
   (0.906 to 0.894), and close_time on sheet_004 (0.964 to 0.954). This is a
   five-sheet aggregate result, not a per-sheet guarantee.
   [Affected-field scored records](date-recognition-detector_sensitivity.json).

2. **Targeted local contrast.** Fixed CLAHE `clipLimit=2.0`, `tileGridSize=(4,4)`
   on LAB luminance after the unchanged B1 pipeline and crop extraction; the
   default PP-OCRv6 medium model then read those crops. No parameter was tuned
   after examining the five-fixture scores. Date stayed at 5/71. Start time
   gained two correct reads; close time gained two and lost two. Its close-time
   mean confidence fell from 0.8043 to 0.8039. [Full scored
   affected-field records](date-recognition-crop_clahe.json).

3. **Bounded contextual reconstruction.** This experiment did **not** edit
   OCR pixels or OCR strings. It accepted a digit-only date as an *inferred
   effective value* only when two surrounding OCR date reads parsed, the date
   difference equalled the row gap in days, and OCR-read DS.No values across
   that interval matched the row sequence. No ground-truth value was used to
   make an inference. It reconstructed sheet_001 row 6 as `2026-08-07` from
   raw `718126`, bounded by raw dates `5/8/26` and `8/8/26` and DS.No reads
   5, 7, 8. The raw date confidence remains 0.8447; the inferred value has
   **no model confidence**. The existing validator only promises
   non-decreasing dates and unique DS numbers; it does not promise one date
   per day. The other four sheets had no parseable date anchors, so this
   technique did not infer their dates. The JSON keeps `ocr_text` and
   `confidence` as the original raw read and puts `effective_value`,
   `effective_source`, and `effective_*` scores in separate fields. [Full
   affected-field records and provenance](date-recognition-bounded_recovery.json).

## Reproduction and limits

Run each variant with `python -m scripts.investigate_date_recognition <variant>`
inside the pinned Docker image used for the PP-OCRv6 baseline. Variants are
`control`, `detector_sensitivity`, `crop_clahe`, `bounded_recovery`, and
`field_routed`. The script asserts
the original 781 records, 213 target OCR records for image experiments, and
the same ordered sheet/row/field/bucket/ground-truth keys after each run,
before writing only the affected-field records. It imports `build_scored_crop`
and `canonicalize`; the locked scoring file is
unchanged. The original report and ground-truth JSON stay unchanged.

This is a small, fixed five-sheet sample. The proposed setting is a measured
**time-field** improvement, not a date fix or proof of generalization. The
CLAHE and recovery spikes are documented measurements; neither is enabled in
the production pipeline.
