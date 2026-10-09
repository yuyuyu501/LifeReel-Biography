# LifeReel Biography Project Workflow

This file contains this repository's defaults. The global Codex
`AGENTS.md` defines task routing, switch semantics, Git safety, and production
boundaries. This file only supplies project-specific switches and commands.

## Workflow switches

```yaml
workflow:
  local_change: 1
  test: 1
  git_sync: 1
  server_update: 0
```

- `local_change: 1`: make approved code or configuration changes in the local
  checkout.
- `test: 1`: run the relevant checks before committing.
- `git_sync: 1`: after validation, review, commit, push to `origin`, and verify
  the remote commit.
- `server_update: 0`: do not update production for ordinary changes. Enable
  this stage only when the user explicitly requests deployment for the current
  task.

## Repository commands

Use the narrowest relevant command for the changed area. For a release-level
change, run all applicable checks below:

```text
pnpm test
pnpm lint
pnpm build
pnpm format
python -m pytest apps/api/tests
ruff check .
docker compose -f compose.production.yaml config --quiet
```

The web package can be checked independently with:

```text
pnpm --filter @lifereel/web test
pnpm --filter @lifereel/web lint
pnpm --filter @lifereel/web build
pnpm --filter @lifereel/web format
```

The mini-program package can be checked independently with:

```text
pnpm --filter @lifereel/mini-program test
pnpm --filter @lifereel/mini-program lint
pnpm --filter @lifereel/mini-program build:weapp
pnpm --filter @lifereel/mini-program build:tt
pnpm --filter @lifereel/mini-program format
```

For backend changes, use the repository's isolated test database settings when
PostgreSQL behavior is involved. Do not use production data or paid providers
for routine tests.

## Git and deployment boundaries

- Use the existing checkout and branch. Do not create a branch or worktree
  unless the user asks for one.
- Preserve unrelated local and server changes.
- Do not commit secrets, `.env` files, personal media, or runtime data.
- `git_sync: 1` means GitHub synchronization; it does not mean that the
  server has been updated.
- `server_update: 0` is the current default. When explicitly enabled, follow
  the global production checks, back up the database and environment, fetch the
  exact pushed commit, run migrations, verify containers and health endpoints,
  and report rollback information.
