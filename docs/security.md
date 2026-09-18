# Security

## Upload pipeline

| Control | Implementation |
|---|---|
| Size limit | `MAX_UPLOAD_BYTES`, enforced while streaming — not after buffering the whole file |
| Type validation | content sniffed with `filetype`, cross-checked against the extension; a mismatch is rejected |
| Format allowlist | images jpg/jpeg/png/webp/tiff · audio wav/mp3/m4a/flac/aac · video mp4/mov/mkv/webm/avi · documents pdf/docx/pptx/xlsx/csv/txt/md/json/html |
| Filename sanitisation | path separators and traversal sequences stripped; the original is kept only as metadata |
| Isolated processing | each job writes to `data/uploads/<job_id>/`, never a shared directory |
| Antivirus hook | `ANTIVIRUS_HOOK` command run per upload; non-zero exit rejects the file |
| Dedupe | content-addressed, so a re-upload cannot be used to multiply processing cost |

## SQL execution

The database agent generates SQL. That is a serious surface, so it is fenced:

1. **Parse, don't regex.** `sqlparse` produces a statement list; more than one statement is rejected
   outright, which kills stacked-query injection.
2. **SELECT only.** `DROP · DELETE · UPDATE · INSERT · ALTER · TRUNCATE · CREATE · GRANT · REVOKE ·
   MERGE · CALL · EXEC · COPY · ATTACH · PRAGMA · INTO OUTFILE` are all rejected. Comments are
   normalised away *before* keyword checking, so `SELECT/*x*/ INTO OUTFILE` cannot slip through.
3. **Table allowlist.** Identifiers outside the source's configured allowlist are rejected.
4. **Forced LIMIT.** Absent → injected at `SQL_MAX_ROWS`. Present and larger → lowered.
5. **Statement timeout.** `SQL_QUERY_TIMEOUT_SECONDS`, enforced at the dialect level.
6. **Parameterisation.** Values are always bound, never concatenated.
7. **Read-only role.** Deployment provisions `spectra_readonly` with `SELECT` only; a
   `verify_read_only()` probe reports whether the role is genuinely restricted.
8. **Full audit.** Every execution — success or failure — writes source, SQL, params, user, row
   count, ok and error to `sql_audit`.

## Object store

`spectra://objects/<aa>/<sha256>.<ext>` is parsed, not string-concatenated. The hash component is
validated against `^[0-9a-f]{6,64}$` and the extension against `^[A-Za-z0-9]{1,8}$`, and the
resolved path is verified to be inside the object root. `spectra://objects/../../etc/passwd` is
rejected before any I/O.

## Connector credentials

Credentials live in a `CredentialStore` (environment or a `0600` secrets file), referenced by
`credential_ref`. They are never written to `SourceDescriptor.connection`, never returned by an API
response, and every log call in the connectors package passes its mapping through `redact()`, which
masks any key matching password/secret/token/key/credential. The API additionally rejects a
`POST /api/sources` whose `connection` contains a secret-looking key.

## REST connectors — SSRF

Hostnames are resolved and checked before the request. Private, loopback, link-local and cloud
metadata ranges (including `169.254.169.254`) are rejected unless the source is explicitly marked
`allow_private_network: true`.

## Graph queries

Cypher cannot parameterise relationship types, so relationship types and node labels are validated
against frozen allowlists before interpolation. Everything else is a bound parameter.

## Application deep links

A link is only emitted when:

- the record id matches the configured `id_pattern` for that entity type;
- the base URL is http/https and carries no credentials;
- the expanded, percent-encoded URL is still under the configured base;
- an injected `verify()` callable confirms the record exists in the database.

`TX1;DROP`, `../admin` and unverified ids produce **no link** rather than a broken or fabricated one.

## Permission-aware search

`PermissionContext` (user, role, source access, denied sources, entity access) is a required argument
on every retrieval path. Filtering happens **before** ranking, and `ctx.cache_key()` is part of every
cache key, so a cached result can never cross a role boundary.

Roles: `admin` (everything), `analyst` (search, investigate, upload, run SQL, autopsy, export),
`viewer` (search and autopsy only). The header shim in `dependencies.py` is the only place that
constructs a context — replacing it with OAuth/OIDC/Keycloak touches that one file.

## Error handling

A uniform envelope `{error, reason, request_id, detail}`. Internal exception types and stack traces
are logged server-side with full context and never returned to the client.

## What is not implemented

Stated plainly, because a security section that claims completeness is not trustworthy:

- No real identity provider — the role header is a development shim.
- No encryption at rest beyond what the underlying stores provide.
- No rate limiting on the API surface (budgets limit agent work, not request volume).
- The antivirus hook is an interface; no scanner is bundled.
- No signed audit log; `sql_audit` is append-only by convention, not cryptographically.
