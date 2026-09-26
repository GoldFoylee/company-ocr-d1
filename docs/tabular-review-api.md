# Tabular review API

The browser review workflow reads sheets through two endpoints:

- `GET /sheets` lists every processed sheet, newest first.
- `GET /sheets/{sheet_id}` returns rows ordered by `row_number`. Every row has
  the physical form's twelve fields in the fixed `FIELD_NAMES` order. Missing
  extractions are explicit empty cells, and `effective_value` uses
  `final_value` when present before falling back to `raw_ocr_value`.

Crop pixels are served by `GET /review/crops/{extraction_id}`. The endpoint
accepts stored JPEG and PNG crops only when their resolved path is contained by
the configured `OCR_CROP_ROOT`. Missing files, unsupported file types, path
escapes, and unknown extraction IDs all return `404`.

## Permanent guest-name exclusion

`guest_name` is excluded before OCR and is never expected in the database. The
read API still treats malformed legacy data defensively: it suppresses guest
records, emits only a fixed empty `guest_name` placeholder in the grid, omits
them from the review queue and verification count, rejects corrections, and
returns `404` for their crop requests. No recognized guest content or crop path
crosses an API response.
