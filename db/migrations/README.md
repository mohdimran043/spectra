# Database migrations

Two directories, two completely different lifecycles.

| Directory | When it runs | Rule |
|-----------|--------------|------|
| `db/baseline/` | Once, on an **empty** database | Never edit to change a live deployment |
| `db/migrations/` | On **every** deploy and on any patch carrying `DB=1` | Append-only, ordered, idempotent |

`scripts/run-migrations.sh` (in a bundle: `./scripts/run-migrations.sh`) applies
both. It records every applied file in `spectra_schema_history` and skips files
already recorded, so rerunning a deploy is safe.

## Naming convention

```
NNNN_short_snake_case_description.sql
```

* `NNNN` is a zero-padded, strictly increasing 4-digit sequence: `0001`, `0002`, …
* Files are applied in plain lexical order, which is why the padding matters.
* Never renumber, never rename and never edit a file that has shipped. A file
  that has been applied anywhere is frozen; correct it with a new migration.
* Never delete a migration. The history table keeps its checksum, and the runner
  warns loudly if a recorded file changes on disk.

## Target database directive

Each file declares which database it belongs to with a comment on its own line:

```sql
-- spectra:target=control      -- SPECTRA control plane (default when absent)
-- spectra:target=enterprise   -- enterprise demo business database
```

The runner reads this directive and connects accordingly. A file with no
directive is applied to the control plane.

## Writing a migration

1. Make it idempotent: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`,
   `ON CONFLICT DO NOTHING`. The runner skips applied files, but an interrupted
   deploy must be safe to retry.
2. Wrap DDL in `BEGIN; … COMMIT;`. PostgreSQL has transactional DDL — use it.
3. Make it **forward-only and non-destructive**. Rollback restores images and
   the UI; it does **not** revert schema. Expand first, contract in a much later
   release once nothing reads the old shape:
   * add a nullable column, backfill, then start writing it
   * never rename or drop a column in the same release that stops using it
4. Guard long index builds on large tables with `CREATE INDEX CONCURRENTLY` in a
   file of their own (it cannot run inside a transaction block — omit the
   `BEGIN`/`COMMIT` in that file and say so in its header).
5. If the migration touches the `enterprise` schema, remember the read-only role:
   new tables inherit `SELECT` through the default privileges set in
   `db/baseline/002_enterprise_demo.sql`, but a new *schema* needs its own
   `GRANT USAGE`.

## Checklist before packaging a release

- [ ] New migration files are present for everything the code now expects
- [ ] Every new file starts at the next free `NNNN`
- [ ] Every new file declares its `-- spectra:target=` when it is not the control plane
- [ ] Reapplying the whole directory on an up-to-date database is a no-op
- [ ] `CHANGELOG.md` mentions any schema change an operator should know about
