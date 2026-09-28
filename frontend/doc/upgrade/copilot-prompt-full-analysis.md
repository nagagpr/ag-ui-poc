# Copilot prompt — Full analysis: move local storage to S3 + PostgreSQL

```
#codebase

ROLE
You are a senior Node.js/TypeScript + AWS engineer. Analyze this repository (sage-node) and
identify ALL changes required for the requirement below. This is an ANALYSIS task: do NOT edit,
create, or delete any file. Output a written report only. Cite file path + line number for every
finding. If something cannot be determined from the code, write "UNKNOWN" and say what would
confirm it. Do not guess.

PROJECT CONTEXT
- sage-node is a Node/Express (TypeScript) "bridge" service: Explorer, Recorder, AI Driver,
  Figma, Ask SAGE and Playwright-backed routes. It also spawns Python scripts from python/
  (ai_driver.py, story_readiness_analyzer.py) and ships a dms/ folder.
- Runs locally with Docker, and in AWS on ECS Fargate (Express Mode) through GitHub Actions
  (.github/workflows/deploy-node.yml): build Dockerfile -> push to ECR -> deploy.
  min-task-count = max-task-count = 1 because state is kept in local JSON/NDJSON files.
- The ECS container's local disk is EPHEMERAL: everything written there is lost on every
  deploy/restart.
- deploy-node.yml already passes these env vars to the container: AWS_REGION, S3_BUCKET_NAME,
  S3_BASE_PREFIX (default "sage"), task-role-arn (ECS_TASK_ROLE_ARN), PLAYWRIGHT_REPO_PATH
  (default /app/data/playwright-repo), SAGE_DATA_ENCRYPTION_KEY, SAGE_AUDIT_HMAC_KEY, JIRA_*,
  FIGMA_TOKEN, AZURE_OPENAI_API_KEY. There are NO database env vars yet.

REQUIREMENT
Stop depending on local disk for persistent data:
1. Binary / file data (screenshots, videos, traces, HTML/JSON reports, recordings, AI-driver
   artifacts, exports) -> Amazon S3, keys: <S3_BASE_PREFIX>/<category>/<...>
   Categories: results-store, recorded-tests, test-reports, explorer-reports, figma-reports,
   ai-driver-artifacts.
2. Structured / queryable data (lifecycle, test repository, agentic missions, Ask SAGE
   sessions + messages, audits, Quality Graph nodes/edges, reconciliation, and any other
   JSON/NDJSON store you find) -> PostgreSQL (Amazon RDS). Postgres stores only records +
   the S3 key of related files, never binaries.
3. Not a data migration: no backfill/import of old local files is needed.
4. Credentials: S3 via the ECS task role (default AWS SDK credential chain, no access keys).
   DB password from AWS Secrets Manager. Nothing hardcoded.
5. Local Docker development must keep working.

WHAT TO ANALYZE

Step 1 — Current storage map
Search src/, python/, dms/, Dockerfile, deploy-node.yml, package.json for:
- Node: fs.writeFile*, fs.appendFile*, fs.createWriteStream, fs.mkdir*, fs.readFile*,
  fs.readdir*, fs.rename, fs.copyFile, fs.unlink, fs.rm, fs-extra, anything exported by
  atomic-file.ts or other file helpers, path.join(...'results-store' | 'data' | 'reports'...).
- Playwright: page.screenshot({ path }), recordVideo / video dir, tracing.stop({ path }),
  outputDir, reporter output folders, storageState files.
- Python: open(...,'w'/'wb'/'a'), json.dump, os.makedirs, pathlib write_text/write_bytes,
  and how results are returned to Node (stdout vs. files).
- Serving: express.static, res.sendFile, res.download, streams of local files.
- Existing S3 code: @aws-sdk/client-s3, PutObjectCommand, GetObjectCommand,
  ListObjectsV2Command, DeleteObjectCommand, presigned URLs, S3_BUCKET_NAME usage.

Step 2 — Classify every finding
For each read/write location output one row:
| # | file:line | function | what data | current target (local path / S3) | read or write |
  pattern (overwrite / append / update-by-id / list dir) | CLASS | already migrated? |
CLASS = S3 (binary/file) | DB (structured record) | TMP (scratch file, OK to stay local if
cleaned up) | CONFIG (shipped in image, read-only) | UNCLEAR (explain).

Step 3 — S3 gap analysis
- Which categories already write AND read via S3, which are partial, which are still local.
- Is there one storage abstraction or scattered fs calls? Recommend one module
  (e.g. src/storage/artifactStore.ts: put/get/getStream/list/delete/exists/presign) and list
  every call site that must be routed through it.
- fs.readdir usages that must become ListObjectsV2 (pagination!).
- Playwright/Python files written to disk: where to upload to S3 after they are produced,
  and where to delete the temp copy.
- Download/view routes: stream from S3 or return presigned URL.
- PLAYWRIGHT_REPO_PATH (/app/data) and dms/: persistent or not? Recommend S3, EFS, or leave.
- Local Docker fallback: how to keep working without S3 (e.g. STORAGE_DRIVER=local|s3).

Step 4 — PostgreSQL data design
For every structured store found:
- store name, file:line, the real TypeScript interface/type (paste it), sample record shape
- read patterns (by id, list, filter fields, sort), relationships (foreign ids)
- encrypted (SAGE_DATA_ENCRYPTION_KEY) or HMAC-signed (SAGE_AUDIT_HMAC_KEY) fields
- references to files (must become an s3_key column)
Then propose the schema as SQL (schema "sage"): CREATE TABLE with Postgres types
(TEXT ids in the app's existing id format, TIMESTAMPTZ, JSONB for nested/variable data,
BYTEA/TEXT for already-encrypted values), primary keys, foreign keys, indexes that match the
real read patterns, audits as append-only. Put numbered files: db/migrations/0001_init_schema.sql,
0002_indexes.sql, plus a schema_migrations tracking table. Show the SQL in the report only.

Step 5 — Required changes, file by file
For each file that must change or be created, give: path | NEW or MODIFY | what changes | why |
risk. Cover at least:
- package.json (@aws-sdk/client-s3, @aws-sdk/s3-request-presigner, pg + @types/pg — or the
  driver/ORM already used in the repo)
- config/env loading (S3_BUCKET_NAME, S3_BASE_PREFIX, AWS_REGION, DB_HOST, DB_PORT, DB_NAME,
  DB_USER, DB_PASSWORD, DB_SSL, STORAGE_DRIVER) — follow the repo's existing config pattern
- storage abstraction + every call site
- DB client (pg.Pool 5–10 connections, SSL for RDS, graceful shutdown) + repository modules
  per store replacing the JSON/NDJSON stores
- /api/health: add S3 and DB checks (non-blocking if appropriate)
- Dockerfile: confirm whether any change is needed (expected: none for S3/pg)
- deploy-node.yml: add DB_HOST/DB_PORT/DB_NAME vars, DB_PASSWORD (and DB_USER) through the
  deploy action's `secrets:` input from Secrets Manager ARN (DB_SECRET_ARN), extend the
  "Check required repository secrets and variables" step
- docker-compose / local dev: add a local postgres service (and optional MinIO/LocalStack for S3)
- tests that touch file storage or stores

Step 6 — AWS / infra prerequisites (list only, don't run anything)
- IAM task role policy: s3:ListBucket (prefix sage/*), s3:GetObject, PutObject, DeleteObject on
  arn:aws:s3:::<bucket>/sage/*. Check which role ECS_TASK_ROLE_ARN points to in the workflow
  comments and flag if it is the infrastructure role instead of an application task role.
- Execution role: secretsmanager:GetSecretValue on the DB secret.
- RDS PostgreSQL in the same VPC/subnets as the ECS service, security group 5432 from the
  ECS service, not publicly accessible, encrypted, backups on.

Step 7 — Final summary
1. DONE (already implemented) — with evidence
2. PENDING for S3 — ordered list
3. PENDING for PostgreSQL — ordered list
4. Blockers for raising max-task-count above 1
5. Open questions for me
6. Suggested implementation order (small, separately deployable steps: S3 first, validate,
   then PostgreSQL)

OUTPUT FORMAT
Markdown with the headings Step 1 … Step 7, tables where listed, file:line citations.
Do not modify any file. At the end, ask me whether to start implementing step 1 of the
suggested order.
```