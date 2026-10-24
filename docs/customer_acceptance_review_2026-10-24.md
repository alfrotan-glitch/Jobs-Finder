# Jobs-Finder — independent customer acceptance review (24 October 2026)

**Decision:** CONDITIONALLY REJECT final turnkey handover. The product can be useful for
daily supervised operation, but a green CI matrix is not proof of functioning
on the owner's actual Windows desktop and Afghanistan network.

This record evaluates delivery as a paying, non-programmer user would:
complete saved work, correct public job data, truthful readiness, and a
documented way to recover without developer intervention.

## Evidence-based acceptance matrix

| Area | Verified in automated CI | Remaining real-world acceptance |
|---|---|---|
| Core profile | Single canonical `profile.yaml`; no inferred or unverified applicant achievements in document exports | Owner review of actual facts and identity |
| Job discovery | Deterministic parsers and source-accounting fixtures; partial scans explicitly differentiated from no jobs | Live ACBAR and ReliefWeb at the owner's network, including listings vs official detail, vacancies, and deadlines |
| Employer and application route | Exact employer field labels; form vs incidental generic contact email; explicit WEB route prioritized | Open at least five live sample official links and validate each application destination |
| Recommendation | Professionally compatible clinical/health roles; hard gaps surface as needs verification or ineligibility | Owner validate at least five requirements and gender/location conditions against official advertisements |
| CV and cover letter | Native PDF and LibreOffice DOCX rendering in CI; evidence-gated claims | Human visual review, formatting, spelling, wording and exact vacancy-specific fit |
| Application history | Deterministic full-ledger pagination and exact counts; applied records survive rescans | Confirm several original prepared/submitted records remain visible after update |
| Job alerts | Deduplicated new matches and deadline stages; persisted locally | Scheduled task and desktop balloon in an interactive Windows user session |
| Local access | Loopback-only default, untrusted-host rejection, response privacy headers and local write-origin guards | Verify no access over LAN and only intended Windows session can see sensitive records |
| Windows launcher | Batch-script assertions and runtime libraries tested; no dependency on Microsoft account | Double-click installation and upgrade on the real Windows computer; confirm launch after restart |
| Backups | SQLite online snapshot, confidential ZIP export, checksum and DB-integrity verification, tampering/path guard tests | User must download a ZIP, verify it independently, store second-drive copy, and test a real offline recovery |
| Full disaster recovery | **Not complete**: no safe verified one-click restore/relink procedure | Develop and test fail-safe recovery on a spare Windows profile / installation before customer sign-off |

## Automatic handover must not claim

- Guaranteed vacancy coverage, unbroken external source connectivity, automatic
  submission, automatic application success, or human eligibility certification.
- A live Windows scheduler or one-click installer tested on the owner's device.
- A true backup/restore solution just because a ZIP can be downloaded.
- A "zero issues" product based only on code coverage or passed tests.

## Minimum final on-device acceptance script

1. Run the project from an updated, clean Windows installation, restart the
   machine, and launch it again by double-click.
2. Open My Profile. Review verified medical credentials, work history, contact
   and languages against the user-provided originals.
3. Run Find Jobs with real internet access; examine source success/partial
   reasons, then open five official postings and compare employers, closing
   dates, eligibility and actual application destinations.
4. Prepare a sample eligible CV/letter, inspect the actual DOCX/PDF files and
   check that no unsupported professional claim is inserted.
5. Mark one test/real application as submitted (only after actual submission),
   run another scan, and verify the status and files persist.
6. Enable the daily task, confirm its actual Windows Task Scheduler action
   points to this checkout, let the next session run, then disable it again.
7. Download the private backup ZIP to a second local drive, use **Verify
   backup ZIP** to check it, and conduct a supervised restore rehearsal in an
   isolated folder/PC without overwriting the working installation.
8. Check all generated links and files are private and non-LAN-accessible.

**Final customer acceptance requires items 1–8 to pass using the user's
actual Windows/network conditions.** The current project and CI cannot prove
these checks from GitHub alone.
