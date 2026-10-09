# Archive — superseded review records

Nothing in this directory is an actionable list. Every file here records a state the project has
already moved past, and is kept only so the owner-confirmed history is not lost.

## The authoritative review artifact lives elsewhere

**`docs/held_responsibility_review.md`** is the single current owner review list. It is regenerated
from the canonical record by `python tools/export_responsibility_review.py`, and the release suite
byte-compares it against that record, so it can never drift out of date.

## Archived here

| File | What it records | Why it is superseded |
| --- | --- | --- |
| `responsibility_review_28_items_pre_recovery.md` | The 28 held duty drafts, reviewed against the normalized profile before the applicant's own CV evidence was recovered (tally CONFIRM 2 / DISCARD 4 / EDIT 22; source `profile.yaml` sha256 `7228c4a2…`). | The evidence-recovery audit rebuilt the applicant-supported responsibilities from the applicant's supplied CV. 6 responsibilities are now verified and 24 drafts remain held, so the 28-item tally no longer describes the current record. The file is preserved byte-for-byte as the frozen owner-confirmed version; its content is intentionally not edited, including its stale counts. |

The restoration that superseded this file is documented in `docs/evidence_recovery_audit.md`,
section 6.
