# Repository Workflow

- Use the existing checkout and branch. Do not create a branch or worktree unless
  the user explicitly requests one.
- Always release in this order: change locally, run relevant tests and checks,
  commit and push to GitHub, fetch the pushed commit on the server, then deploy.
- Never edit application source directly on the production server. If GitHub is
  unreachable there, use a verified Git bundle of the same pushed commit.
- Preserve local and server changes. Require a clean server checkout before a
  fast-forward update; never overwrite unexpected changes.
- Before deployment, check active jobs, back up the database and environment,
  and retain the previous runtime images for rollback.
- Do not commit secrets, environment files, personal media, or runtime data.
- Use isolated databases and mock providers for tests. Do not invoke paid AI,
  SMS, payment, or video services as part of routine release verification.
- A release is complete only after required migrations finish, affected services
  run the new code, health checks pass, and local/GitHub/server commit IDs match.
  Matching Git commits alone does not prove that running containers were updated.
- Report the deployed commit, runtime checks, migration version, and backup path.
