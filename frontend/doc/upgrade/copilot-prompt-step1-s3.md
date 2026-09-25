# Copilot prompt — Step 1 (S3 storage upgrade)

Files to attach in VS Code / Copilot Chat: `1.S3_MIGRATION.md`

```
I need to implement Phase 1 of a storage upgrade for this repo (sage-node), specified in
#file:1.S3_MIGRATION.md. Read that file fully before making any changes.

IMPORTANT: this is NOT a data migration. There is no existing local data that needs to be
preserved, backfilled, or copied into S3 — local disk storage is already ephemeral (lost on
every task restart today), so there's nothing of value sitting there. Your job is to make the
application write NEW artifacts to S3 going forward, starting from the next deploy. Do not
write any code that scans local disk for pre-existing files and uploads them to S3 — that
logic isn't needed and shouldn't exist.

Before writing any code:
1. Find the actual module(s) that currently read/write local files under results-store/,
   recorded-tests/, test-reports/, explorer-reports/, figma-reports/, ai-driver-artifacts/
   (search for fs.writeFile, fs.readFile, fs.readdir, fs.unlink against these paths).
2. Report back what you find — file paths, whether it's one central module or scattered
   across routes, and whether any reads are directory-listing (fs.readdir) vs. single-file
   reads — before changing anything. This matters because S3's ListObjectsV2 has different
   semantics than fs.readdir, per the note in 1.S3_MIGRATION.md section 4.
3. Only after I confirm, implement the storage abstraction 1.S3_MIGRATION.md section 4
   describes (put/get/list/delete), backed by @aws-sdk/client-s3, and route the existing
   local-file call sites through it. Keep the six category names unchanged; keys should be
   prefixed with S3_BASE_PREFIX/<category>/ (default "sage").

Constraints:
- Do NOT touch anything related to PostgreSQL — that's a separate phase, out of scope here.
- Do NOT write any local-to-S3 backfill/import logic — see the note above, there's nothing to
  migrate.
- Do NOT remove the existing local filesystem code paths yet — keep the old path as a fallback
  until the new one is confirmed working in a real deploy. Add the new path alongside the old
  one, or behind a flag if that fits this codebase's existing conventions better — tell me
  which approach fits before picking one.
- Do NOT hardcode the bucket name, region, or any credential. Use environment variables
  named exactly AWS_REGION, S3_BUCKET_NAME, S3_BASE_PREFIX (per section 6 of the doc) —
  read them the same way this codebase already reads its other env vars (match existing
  config-loading conventions, don't introduce a new pattern).
- Apply the Dockerfile and deploy-node.yml changes exactly as diffed in 1.S3_MIGRATION.md
  sections 5 and 6 — flag anything in those diffs that doesn't match what's actually in this
  repo's current Dockerfile/deploy-node.yml rather than silently reconciling it.
- The IAM role for this is named sage-storage-task-role — NOT sage-ecs-task-role, which already
  exists in this account but is provisioned for a different purpose (the Express Mode
  infrastructure role). Don't confuse the two or suggest reusing sage-ecs-task-role.
- Match this repo's existing code style, error handling patterns, and TypeScript conventions.
  Don't refactor anything outside what's needed for this upgrade.
- List every file you plan to touch before editing, and wait for my go-ahead.
```
