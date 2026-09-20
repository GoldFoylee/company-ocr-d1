# Anonymized fixture convention

This directory is the only location in the repository for fixture images derived from real
source sheets. The repository is permanently public, so anonymization is mandatory before a
file is staged or committed.

For every image placed here:

1. Black out the **Guest Name** cell in the image before copying the image into this directory.
   The redaction must contain no readable name pixels or recoverable name text.
2. Add matching ground-truth JSON with the same filename stem as the image.
3. For every row whose Guest Name cell was redacted, set `guest_name` to `null` and
   `guest_name_excluded` to `true` in that JSON.
4. Do not put a real guest name string anywhere in the JSON, including values, keys, notes,
   comments, metadata, or filenames.

Raw, unredacted fixtures belong only in the local `tests/fixtures/raw/` directory. That path is
ignored by Git, and repository safeguards reject any file under it that is force-added.
