# Privacy and reference-contact boundary

## Public canonical profile

`profile.yaml` is the sole runtime applicant profile. It is intentionally
tracked and contains the verified employment/credential facts required for
matching and document generation. It must not contain reference-contact PII.

The profile carries only this policy boundary:

- references require an explicit vacancy need;
- release requires explicit owner approval for that specific vacancy;
- the default release state is `NOT_RELEASED`.

The canonical-profile completeness contract (`utils.profile`) checks that the
public file has this boundary and no `professional_references` field.

## Private reference metadata

If the owner elects to keep the supplied referee contact details available
locally, the file must be outside this repository. Set an absolute external
path through `JOBS_FINDER_PRIVATE_REFERENCES_PATH`; repository-relative paths
are rejected by `utils.private_references`.

There is no default filename, fallback path, browser store, SQLite table, cache,
or import mechanism for references. The private loader rejects every request
unless both conditions are supplied programmatically:

1. the vacancy explicitly requires references; and
2. the owner has explicitly approved release for that vacancy.

Normal Jobs-Finder workflows do **not** call that loader. They use a generic
manual checklist for reference requirements. The system never automatically
puts reference names, roles, phones, or email addresses into a CV, cover letter,
dashboard response, recommendation, generated package, database row, cache, or
log.

## Local artifacts and dashboard

Generated application artifacts and SQLite data are ignored by Git. The local
dashboard uses no-store response headers and is loopback-first; it is not an
authenticated public service. Do not expose it to a shared/public network
without access control and TLS.

CV previews are temporary, bounded uploads and do not create a profile,
reference store, cache, or backup. No feature submits applications or bypasses
CAPTCHA, login, or MFA.
