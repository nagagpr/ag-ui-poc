# Copilot prompt — Step 2 (PostgreSQL storage upgrade)

Files to attach in VS Code / Copilot Chat: `1.S3_MIGRATION.md`, `2.POSTGRES_MIGRATION.md`,
`db/migrations/0001_init_schema.sql`, `db/migrations/0002_indexes.sql`

```
I need to implement Phase 2 of a storage upgrade for this repo (sage-node), specified in
#file:2.POSTGRES_MIGRATION.md. This builds on Phase 1 (#file:1.S3_MIGRATION.md), which should
already be implemented and working in this repo — confirm that before doing anything else,
and stop if it isn't.

IMPORTANT: this is NOT a data migration. There is no existing database, and the structured
data currently sitting in local JSON/NDJSON files is not being converted or imported — it's
ephemeral today, same as the artifacts handled in Phase 1. Your job is to make the application
write NEW structured records to PostgreSQL going forward, starting from a clean, empty schema.
Do not write any code that reads old local JSON/NDJSON files and imports their contents into
Postgres — that logic isn't needed and shouldn't exist.

Infrastructure provisioning (the RDS instance, its security group, and the Secrets Manager
entry) is NOT your job and is NOT automated. I am running the AWS CLI commands in
2.POSTGRES_MIGRATION.md Section 1a myself, by hand, outside of this session. Do not attempt to
run any AWS CLI command, do not attempt to provision any AWS resource, and do not assume any
specific DB_HOST/DB_PORT/secret ARN value — those only exist once I've run Section 1a and will
be set as real environment variables/GitHub secrets afterward. Your scope is strictly:
application code, plus the deploy-node.yml and Dockerfile changes.

Before writing any code:
1. Find whatever in this codebase currently reads/writes the "structured" data described in
   2.POSTGRES_MIGRATION.md section 3 — lifecycle state, test-repository metadata, agentic
   mission records, Ask SAGE sessions, audits, Quality Graph, reconciliation data. This is
   likely the local JSON/NDJSON state store referenced in deploy-node.yml's comment about
   max-task-count being pinned to 1.
2. Compare what you find against the proposed schema in
   #file:db/migrations/0001_init_schema.sql and #file:db/migrations/0002_indexes.sql. The
   schema is explicitly marked a PROPOSAL in the doc, not derived from real code — report back
   any mismatch (missing fields, different relationships, a field that doesn't fit any table)
   before I decide whether to adjust the SQL files or the application code to reconcile them.
3. Specifically check how SAGE_DATA_ENCRYPTION_KEY and SAGE_AUDIT_HMAC_KEY are currently used
   — the doc assumes the app already encrypts/signs some of this data at the application layer
   and that Postgres should just store the resulting values unchanged. Confirm or correct that
   assumption.
4. Only after I confirm findings from 1-3, implement a database client module (connection pool,
   using whatever Postgres driver fits this codebase's existing dependency conventions — don't
   introduce a new one without asking) that reads DB_HOST, DB_PORT, DB_NAME, DB_USER,
   DB_PASSWORD from environment variables exactly as named in section 8 of the doc, and route
   the confirmed call sites through it.

Constraints:
- Do NOT touch the S3 integration from Phase 1 — it should already be working; don't refactor
  it as part of this change.
- Do NOT write any local-to-Postgres backfill/import logic — see the note above, there's
  nothing to migrate.
- Do NOT remove the existing local JSON/NDJSON code paths yet — keep the old path as a fallback
  until the new one is confirmed working in a real deploy, same rule as Phase 1.
- Do NOT hardcode any DB credential, host, or port anywhere, including in tests or sample
  configs.
- Do NOT write or modify any SQL migration file — the two provided are the schema to code
  against. If the schema needs to change based on what you find in step 2, tell me and I'll
  decide whether to add a new numbered migration file (0003_...), rather than editing the
  existing ones.
- Apply the deploy-node.yml changes exactly as diffed in 2.POSTGRES_MIGRATION.md section 7 —
  flag anything that doesn't match what's actually in this repo's current deploy-node.yml
  (which should already reflect the Phase 1 changes) rather than silently reconciling it.
- No Dockerfile changes are expected for this phase — confirm that's still true once you know
  which Postgres client library this codebase ends up using, and flag it if not.
- Match this repo's existing code style, error handling, and TypeScript conventions. Don't
  refactor anything outside what's needed for this upgrade.
- List every file you plan to touch before editing, and wait for my go-ahead.
```
