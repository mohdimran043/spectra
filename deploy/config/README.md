# Config templates

Everything in this directory is copied to `$APP_ROOT/config/` by
`scripts/deploy.sh` **on the first deploy only**. Operator edits are never
overwritten by a later deploy, upgrade or patch.

| File | Purpose |
|------|---------|
| `spectra-overrides.env` | Optional env overrides mounted into `api` and `worker`. Only affects keys the compose file does not already set. |

Secrets do not belong here. Every credential lives in `.env`, which is the one
place the deploy scripts check for leftover `CHANGE_ME` values.
