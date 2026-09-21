# GitHub Actions → Amazon ECR → Amazon ECS: `sage-ui` Deployment Setup

One-time setup + repeatable deployment guide for the `sage-ui` Next.js application, deployed via
GitHub Actions → Amazon ECR → Amazon ECS (Fargate, classic task-definition/service model).

> **Adapted from, not copied from, [`GITHUB_ACTIONS_ECS_SETUP.md`](GITHUB_ACTIONS_ECS_SETUP.md).**
> That proven pipeline uses **ECS Express Mode** for a single standalone public service. `sage-ui`
> could technically use Express Mode on its own (it is public, single-service), but it shares an
> ECS cluster (`sage-prod`) and a GitHub Actions IAM role with `sage-api`, which *cannot* use
> Express Mode (it needs an internal ALB — see
> [`API_GITHUB_ACTIONS_ECS_SETUP.md`](API_GITHUB_ACTIONS_ECS_SETUP.md)). Running one service on
> Express Mode and the other on classic ECS in the same cluster adds inconsistent operational
> patterns for no real benefit, so this guide also uses classic ECS task definitions + services,
> reusing the baseline's proven OIDC-role / no-stored-keys pattern.

> ⚠️ **This session could not read the actual `sage-ui` source, Dockerfile, `next.config.mjs`, or
> `.github/workflows/deploy-ui.yml`** (the repository lives in a location this session has no
> access to). Every value below is either carried over from `SAGE_UI_AWS_DEPLOYMENT.md` (already
> decided, cited inline) or marked **`VERIFY/REQUIRED`** where it must be confirmed against the
> real repository before you run this for the first time.

## What the pipeline does

```text
git push (main, paths: sage-ui/**)
      ↓
GitHub Actions (deploy-ui.yml)
      ├── assume IAM role via OIDC          (no AWS access keys stored anywhere)
      ├── docker build sage-ui/             (Next.js standalone build)
      ├── push image to Amazon ECR          sage-ui:<git-sha>  and  sage-ui:latest
      ├── register new ECS task definition revision (family: sage-ui)
      └── update ECS service sage-ui on cluster sage-prod, wait for stability
      ↓
Public ALB (HTTPS 443) → sage-ui Fargate tasks (port 3000)
      ↓
Browser: https://<domain-or-alb-dns>/sage5
      ↓ (server-side Next.js rewrite of /api/*)
Internal sage-api ALB (SAGE_API_ORIGIN) → sage-api Fargate tasks (port 8000)
```

This depends on `sage-api` already being deployed and its internal ALB DNS name known — deploy
the API first (per [`API_GITHUB_ACTIONS_ECS_SETUP.md`](API_GITHUB_ACTIONS_ECS_SETUP.md)), then the
UI, matching `SAGE_API_AWS_DEPLOYMENT.md` §12's stated ordering.

## Values used throughout

| Placeholder / value | Meaning | Source |
|---|---|---|
| `107094296439` | AWS Account ID (`QEAI.DEV`) | `SAGE_UI_AWS_DEPLOYMENT.md` §0 |
| `us-east-1` | Region | `SAGE_UI_AWS_DEPLOYMENT.md` §0 |
| `sage-ui` | ECR repo name, ECS task-def family, ECS service name, container name | `SAGE_UI_AWS_DEPLOYMENT.md` §3 |
| `sage-prod` | Shared ECS cluster (also hosts `sage-api`) | `SAGE_UI_AWS_DEPLOYMENT.md` §3 |
| `sage-github-actions-deploy-role` | IAM role GitHub Actions assumes via OIDC — **shared with `sage-api`'s workflow** | `SAGE_UI_AWS_DEPLOYMENT.md` §7 secret value |
| `sage-ecs-task-execution-role` / `sage-ecs-task-role` | ECS execution/task roles | `SAGE_UI_AWS_DEPLOYMENT.md` §5 |
| `<GITHUB_ORG>/<REPO_NAME>` | GitHub org/user and repository name | **VERIFY/REQUIRED** — not stated in either source doc |
| `3000` | Container port | `SAGE_UI_AWS_DEPLOYMENT.md` §1 |
| `/` | Health check path | `SAGE_UI_AWS_DEPLOYMENT.md` §3 — **VERIFY/REQUIRED**, see "Health checks" below for a caveat |
| `sage-ui/Dockerfile` | Dockerfile location | `SAGE_UI_AWS_DEPLOYMENT.md` §1 — **VERIFY/REQUIRED**, file not read |
| `.github/workflows/deploy-ui.yml` | Workflow file path | `SAGE_UI_AWS_DEPLOYMENT.md` §1 — **VERIFY/REQUIRED**, file not read |
| `SAGE_API_ORIGIN` | Internal API ALB DNS name, consumed by `next.config.mjs` rewrites | `SAGE_UI_AWS_DEPLOYMENT.md` §2 — real value comes from API guide Step 7 |

## Prerequisites

- Complete [`API_GITHUB_ACTIONS_ECS_SETUP.md`](API_GITHUB_ACTIONS_ECS_SETUP.md) Steps 1–9 first —
  you need the internal ALB DNS name it produces.
- The same GitHub repository as `sage-api` (see that guide's Prerequisites for why) pushed to
  `main`, containing `sage-ui/`. **VERIFY/REQUIRED**.
- A VPC with at least two **public** subnets (for the public ALB) and reuse of the **private**
  subnets from the API guide (for the UI's own Fargate tasks — the tasks themselves don't need to
  be public, only the ALB does). **VERIFY/REQUIRED**: get actual subnet IDs.
- A registered domain + ACM certificate if you want a custom HTTPS domain instead of the raw ALB
  DNS name. **VERIFY/REQUIRED** — `SAGE_UI_AWS_DEPLOYMENT.md` §3 lists ACM/Route 53 as optional;
  without them you'll access the app at `https://<alb-dns-name>`, which still needs *some*
  certificate (see Step 6 — ACM supports certs for ALB DNS names too, or use a self-managed cert,
  or accept HTTP-only for a POC and skip HTTPS entirely — decide this before Step 6).

---

> **Account status confirmed 2026-09-21**: account `107094296439` currently has **none** of the
> resources below — no OIDC provider, no `sage-github-actions-deploy-role`, no
> `sage-ecs-task-execution-role`, no `sage-ecs-task-role`. Steps 1–3 create all of them from
> scratch. These three roles and the OIDC provider are **account-wide, not per-service** — you
> create each one exactly once, and `sage-api`'s deployment guide (Steps 1–4 there) uses the
> identical resources. If you follow this UI guide before the API guide, you still only create
> them once; when you later open the API guide, its Steps 1–4 will already be satisfied — just
> confirm the inline policy (Step 2 below) covers both `sage-api` and `sage-ui`, which it does as
> written.

## Step 1 — Add GitHub as an OIDC identity provider

IAM Console → **Identity providers** → **Add provider**:

| Field | Value |
|---|---|
| Provider type | **OpenID Connect** |
| Provider URL | `https://token.actions.githubusercontent.com` |
| Audience | `sts.amazonaws.com` |

Click **Add provider**. This is a one-time, account-level resource shared by both services' GitHub
Actions workflows.

Or via CLI (get the thumbprint dynamically rather than hardcoding one, since GitHub rotates it):

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list $(echo | openssl s_client -servername token.actions.githubusercontent.com -showcerts -connect token.actions.githubusercontent.com:443 2>/dev/null | openssl x509 -fingerprint -sha1 -noout | cut -d= -f2 | tr -d ':') \
  --region us-east-1
```

## Step 2 — IAM role: `sage-github-actions-deploy-role`

This single role is assumed by **both** `deploy-ui.yml` and `deploy-api.yml`.

IAM Console → **Roles** → **Create role**:

1. Trusted entity type: **Web identity**
2. Identity provider: `token.actions.githubusercontent.com` — Audience: `sts.amazonaws.com`
3. GitHub organization / repository / branch: `<GITHUB_ORG>`, `<REPO_NAME>`, `main` —
   **VERIFY/REQUIRED**
4. **Next** → Add permissions: leave everything unticked → **Next**
5. Role name: `sage-github-actions-deploy-role` → **Create role**
6. Open the role → **Permissions** → **Add permissions ▾ → Create inline policy** → **JSON** →
   paste (already scoped to both `sage-ui` and `sage-api`) → policy name `deploy-sage-services`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "EcrPushBothRepos",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:DescribeRepositories",
        "ecr:DescribeImages"
      ],
      "Resource": [
        "arn:aws:ecr:us-east-1:107094296439:repository/sage-api",
        "arn:aws:ecr:us-east-1:107094296439:repository/sage-ui"
      ]
    },
    {
      "Sid": "EcsDeployBothServices",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition",
        "ecs:DescribeServices",
        "ecs:UpdateService",
        "ecs:DescribeClusters",
        "ecs:ListTasks",
        "ecs:DescribeTasks",
        "ecs:TagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassEcsRoles",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::107094296439:role/sage-ecs-task-execution-role",
        "arn:aws:iam::107094296439:role/sage-ecs-task-role"
      ]
    },
    {
      "Sid": "Logs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:DescribeLogGroups"],
      "Resource": "*"
    }
  ]
}
```

Trust policy (the wizard writes this from step 3 above — open the role's **Trust relationships**
tab and confirm it looks like this):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::107094296439:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:<GITHUB_ORG>/<REPO_NAME>:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

If the console wizard doesn't offer the org/repo/branch fields directly, choose **Custom trust
policy** and paste the JSON above instead.

## Step 3 — IAM roles: `sage-ecs-task-execution-role` and `sage-ecs-task-role`

Two separate roles — one for the ECS agent (pulls the image, ships logs), one for the running
application (only needed if the app itself calls an AWS SDK).

**`sage-ecs-task-execution-role`** — IAM Console → **Create role** → Trusted entity: **Custom
trust policy** → paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Principal": { "Service": "ecs-tasks.amazonaws.com" }, "Action": "sts:AssumeRole" }
  ]
}
```

→ **Next** → attach managed policy **`AmazonECSTaskExecutionRolePolicy`** → Role name
`sage-ecs-task-execution-role` → **Create role**.

**`sage-ecs-task-role`** — same trust policy as above → Role name `sage-ecs-task-role` → attach
**no managed policies** at creation time → **Create role**. Add an inline policy later only if
`sage-ui`'s or `sage-api`'s own code calls an AWS SDK at runtime (e.g., Secrets Manager, S3) —
**VERIFY/REQUIRED**, not indicated in either source doc.

CLI equivalent for both:

```bash
aws iam create-role --role-name sage-ecs-task-execution-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --region us-east-1
aws iam attach-role-policy --role-name sage-ecs-task-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam create-role --role-name sage-ecs-task-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --region us-east-1
```

---

## Step 4 — Create the ECR repository

```bash
aws ecr create-repository --repository-name sage-ui --region us-east-1 --image-scanning-configuration scanOnPush=true
```

Resulting image URI: `107094296439.dkr.ecr.us-east-1.amazonaws.com/sage-ui`

## Step 5 — Create the CloudWatch log group

```bash
aws logs create-log-group --log-group-name /ecs/sage-ui --region us-east-1
```

---

## Step 6 — Networking: public ALB, target group, security groups, HTTPS

**VERIFY/REQUIRED**: substitute real VPC/subnet IDs and, if using a custom domain, a real ACM
certificate ARN.

1. **Security group `sage-ui-alb-sg`**:
   - Inbound: TCP `443` from `0.0.0.0/0`; optionally TCP `80` from `0.0.0.0/0` for an HTTP→HTTPS
     redirect.
   - Outbound: TCP `3000` to `sage-ui-ecs-sg`.
2. **Security group `sage-ui-ecs-sg`**:
   - Inbound: TCP `3000` from `sage-ui-alb-sg`.
   - Outbound: TCP `80` to `sage-api-alb-sg` (created in the API guide's Step 7 — the internal
     API ALB listens on plain HTTP `80`, not `8000`; the target group forwards to `8000` on the
     tasks, but the ALB's own listener is `80`). Also allow `443` outbound for ECR/CloudWatch.
3. **Public ALB**: EC2 → **Load Balancers → Create Application Load Balancer**:
   - Scheme: **Internet-facing**
   - Subnets: two **public** subnets — `<PUBLIC_SUBNET_ID_1>`, `<PUBLIC_SUBNET_ID_2>`
   - Security group: `sage-ui-alb-sg`
   - Listener: HTTPS `443`, attach ACM certificate `<ACM_CERTIFICATE_ARN>` — **VERIFY/REQUIRED**:
     request one via **ACM → Request certificate** for your domain, or for the raw ALB DNS name
     (AWS does not issue public certs for `*.elb.amazonaws.com`, so a bare ALB DNS name **cannot**
     have a browser-trusted HTTPS cert — you need either a custom domain, or accept HTTP-only for
     this POC and revisit before any real production use).
4. **Target group `sage-ui-tg`**:
   - Type: **IP**
   - Protocol/port: HTTP `3000`
   - Health check path: `/` — see caveat below
5. Optional: Route 53 alias record `<DOMAIN_NAME>` → the ALB.

### Health-check path caveat — VERIFY/REQUIRED

`SAGE_UI_AWS_DEPLOYMENT.md` §1 states "the root route redirects to `/sage5`". If the health check
hits `/` and the app returns an HTTP **redirect** (3xx) rather than a 200, the ALB target-group
health check (which by default expects `200` and does not follow redirects) will mark every task
**unhealthy**, even though the app is running fine. Before relying on `/` as the health check
path: confirm whether that redirect is a server-side 3xx or a client-side Next.js router push (the
latter still serves the initial HTML with a 200 and would be fine). If it's a real HTTP redirect,
either add a dedicated `/api/health`-style route that returns 200 with no redirect, or configure
the target group's health-check "success codes" field to include `200,301,302,307,308`.

---

## Step 7 — ECS task definition (family `sage-ui`)

```json
{
  "family": "sage-ui",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::107094296439:role/sage-ecs-task-execution-role",
  "taskRoleArn": "arn:aws:iam::107094296439:role/sage-ecs-task-role",
  "containerDefinitions": [
    {
      "name": "sage-ui",
      "image": "107094296439.dkr.ecr.us-east-1.amazonaws.com/sage-ui:latest",
      "essential": true,
      "portMappings": [{ "containerPort": 3000, "protocol": "tcp" }],
      "environment": [
        { "name": "NODE_ENV", "value": "production" },
        { "name": "SAGE_API_ORIGIN", "value": "http://<sage-api-internal-alb-dns-name>" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/sage-ui",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

```bash
aws ecs register-task-definition --cli-input-json file://sage-ui-task-def.json --region us-east-1
```

Replace `<sage-api-internal-alb-dns-name>` with the actual value from the API guide's Step 7.

**VERIFY/REQUIRED — build-time vs. runtime env var**: `SAGE_UI_AWS_DEPLOYMENT.md` §2 says
`next.config.mjs` uses `SAGE_API_ORIGIN` for Next.js rewrites. In Next.js, if `next.config.mjs`
reads `process.env.SAGE_API_ORIGIN` **inside** the `async rewrites()` function, that function runs
per-request in the running Node server, so setting it as an ECS **runtime** environment variable
(as above) is sufficient — no Docker build arg needed. If instead the config module reads it at
the top level (evaluated once, during `next build`), the value gets baked into the built image at
build time, and the runtime environment variable above would be ignored. Open
`sage-ui/next.config.mjs` and confirm which pattern is used before your first real deployment — if
it's the build-time pattern, add `--build-arg SAGE_API_ORIGIN=...` to the Docker build step in
Step 11 as well, and rebuild any time the API's ALB DNS name changes.

---

## Step 8 — ECS service `sage-ui`

Console: **ECS → cluster `sage-prod` → Create service** (create the cluster in the API guide's
Step 9 if not already done — it's shared).

| Field | Value |
|---|---|
| Launch type | Fargate |
| Task definition family | `sage-ui` |
| Service name | `sage-ui` |
| Desired tasks | `2` (prod) / `1` (lower envs) |
| Subnets | private subnets (tasks don't need public IPs — the ALB is the public entry point) |
| Public IP | Disabled |
| Security group | `sage-ui-ecs-sg` |
| Load balancer | public ALB from Step 6 → target group `sage-ui-tg` on port `3000` |
| Deployment | Enable circuit breaker + rollback; health check grace period `60`s |

```bash
aws ecs create-service \
  --cluster sage-prod \
  --service-name sage-ui \
  --task-definition sage-ui \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<PRIVATE_SUBNET_ID_1>,<PRIVATE_SUBNET_ID_2>],securityGroups=[<sage-ui-ecs-sg-id>],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=<sage-ui-tg-arn>,containerName=sage-ui,containerPort=3000" \
  --health-check-grace-period-seconds 60 \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}" \
  --region us-east-1
```

---

## Step 9 — GitHub repository secrets

Same secret as the API guide's Step 11 — do not add it twice, GitHub secrets are per-repository,
not per-workflow.

| Secret name | Value |
|---|---|
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | `arn:aws:iam::107094296439:role/sage-github-actions-deploy-role` |

## Step 10 — GitHub repository variables

| Variable name | Value |
|---|---|
| `AWS_REGION` | `us-east-1` |
| `ECS_CLUSTER` | `sage-prod` |
| `ECS_UI_SERVICE` | `sage-ui` |
| `ECS_UI_TASK_DEFINITION` | `sage-ui` |
| `SAGE_API_ORIGIN` | `http://<sage-api-internal-alb-dns-name>` — from the API guide's Step 7 |

---

## Step 11 — Workflow file: `.github/workflows/deploy-ui.yml`

**VERIFY/REQUIRED**: not readable this session — reconcile against the real file.

```yaml
name: Deploy sage-ui

on:
  push:
    branches: [main]
    paths:
      - "sage-ui/**"
      - ".github/workflows/deploy-ui.yml"
  workflow_dispatch: {}

permissions:
  id-token: write
  contents: read

env:
  AWS_REGION: ${{ vars.AWS_REGION }}
  ECR_REPOSITORY: sage-ui
  ECS_CLUSTER: ${{ vars.ECS_CLUSTER }}
  ECS_SERVICE: ${{ vars.ECS_UI_SERVICE }}
  ECS_TASK_DEFINITION_FAMILY: ${{ vars.ECS_UI_TASK_DEFINITION }}
  CONTAINER_NAME: sage-ui

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials via OIDC
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_GITHUB_ACTIONS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to Amazon ECR
        id: ecr-login
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push image
        id: build-image
        env:
          ECR_REGISTRY: ${{ steps.ecr-login.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build \
            --build-arg SAGE_API_ORIGIN="${{ vars.SAGE_API_ORIGIN }}" \
            -t "$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" \
            -t "$ECR_REGISTRY/$ECR_REPOSITORY:latest" \
            sage-ui
          docker push "$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG"
          docker push "$ECR_REGISTRY/$ECR_REPOSITORY:latest"
          echo "image=$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" >> "$GITHUB_OUTPUT"
          # NOTE: this build-arg line is only needed if next.config.mjs reads
          # SAGE_API_ORIGIN at build time — see Step 7's caveat. Remove it if
          # the runtime env var alone is confirmed sufficient.

      - name: Download current task definition
        run: |
          aws ecs describe-task-definition \
            --task-definition "$ECS_TASK_DEFINITION_FAMILY" \
            --query taskDefinition \
            > task-definition.json

      - name: Render new task definition
        id: render-task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: task-definition.json
          container-name: ${{ env.CONTAINER_NAME }}
          image: ${{ steps.build-image.outputs.image }}

      - name: Deploy to ECS and wait for stability
        uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          task-definition: ${{ steps.render-task-def.outputs.task-definition }}
          service: ${{ env.ECS_SERVICE }}
          cluster: ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true
```

---

## First-time AWS setup vs. normal deployment

**First-time setup (once per environment)** — Steps 1–8: OIDC provider, the shared IAM role, and
the two ECS roles (create these once — the API guide's Steps 1–4 point at the identical resources,
so whichever guide you run first is the one that actually creates them), ECR repo, log group,
public ALB/target group/security groups/ACM cert, initial task definition, initial
`ecs create-service`. Steps 9–11 (GitHub secrets/variables/workflow) are one-time.

**Normal deployment (every subsequent change)** — `git push` to `main` touching `sage-ui/**`, or
**Actions → Deploy sage-ui → Run workflow**. No console steps required, unless `SAGE_API_ORIGIN`
changes (e.g., the API's ALB was recreated) — in that case, update the GitHub variable in Step 10
and the task-definition environment value in Step 7, then redeploy.

---

## Health checks

- Target group: path `/` (see the caveat under Step 6 about redirects — resolve that before
  trusting this in production), success codes default `200` unless widened.
- Application-level: `curl -I https://<alb-dns-or-domain>/sage5` should return `200`.
- End-to-end: `curl https://<alb-dns-or-domain>/api/health` should proxy through to `sage-api` and
  return the JSON documented in the API guide's "Health checks" section — if this returns a 502/
  504 instead, the UI→API path is broken (see Troubleshooting).

## Networking / security-group requirements (summary)

See Step 6. `sage-ui-alb-sg` accepts `443` (and optionally `80`) from the internet;
`sage-ui-ecs-sg` only accepts `3000` from `sage-ui-alb-sg` and must be allowed **outbound** to
`sage-api-alb-sg` on `80` for the API proxy to work.

## Load balancer / HTTPS

Required — this is the public entry point. See Step 6's ACM caveat: a bare `*.elb.amazonaws.com`
DNS name cannot get a browser-trusted certificate; use a custom domain with Route 53 + ACM, or
knowingly run HTTP-only for this POC.

## UI → API configuration

`SAGE_API_ORIGIN` (Step 7/10) must equal the API's internal ALB DNS name from
[`API_GITHUB_ACTIONS_ECS_SETUP.md`](API_GITHUB_ACTIONS_ECS_SETUP.md) Step 7, with `http://` (not
`https://` — the internal ALB has no cert) and no trailing slash — **VERIFY/REQUIRED** against
what `next.config.mjs`'s rewrite rule expects (trailing slash handling varies by implementation).

## CORS

Not required for the primary path — see the API guide's CORS section; the same reasoning applies
here (Next.js server-side rewrite keeps this same-origin from the browser's perspective).

## Production configuration

- `NODE_ENV=production` (Step 7) — required for Next.js to serve the optimized `node server.js`
  standalone build rather than a dev server.
- Desired task count `2` for actual production use, per both source docs; `1` is acceptable for a
  POC/demo where a brief outage during deployment is tolerable.
- **VERIFY/REQUIRED**: check `sage-ui/package.json` for the exact production start script; this
  guide assumes `node server.js` as stated in `SAGE_UI_AWS_DEPLOYMENT.md` §1, consistent with a
  Next.js `output: "standalone"` build.

---

## Verification / testing steps

1. GitHub → **Actions** → `Deploy sage-ui` run → all steps green.
2. AWS Console → **ECR → sage-ui** → new image tag matching the commit SHA.
3. AWS Console → **ECS → sage-prod → sage-ui → Deployments** → new revision `PRIMARY`, running
   count == desired count.
4. AWS Console → **EC2 → Target Groups → sage-ui-tg → Targets** → all `healthy`.
5. Browser (or `curl`): `https://<alb-dns-or-domain>/sage5` loads the Mission Center UI.
6. `curl https://<alb-dns-or-domain>/api/health` returns the API's health JSON, confirming the
   full proxy chain UI → internal ALB → API works.

## How to check GitHub Actions logs

GitHub → repository → **Actions** → `Deploy sage-ui` → select the run → `deploy` job → expand
steps. Docker/npm build failures appear under "Build and push image"; ECS deployment failures
(including circuit-breaker rollback reasons) appear under "Deploy to ECS and wait for stability".

## How to check ECS task/service logs in CloudWatch

AWS Console → **CloudWatch → Logs → Log groups → `/ecs/sage-ui`** → newest stream
`ecs/sage-ui/<task-id>` → stdout/stderr of `node server.js`. Look here for Next.js server startup
errors, and for proxy errors if `/api/*` rewrites are failing (a `fetch failed` or `ECONNREFUSED`
pointing at the API's internal ALB DNS name usually means `SAGE_API_ORIGIN` is wrong or the API
service is down).

## How to verify the final application URL

EC2 Console → **Load Balancers → sage-ui-alb → DNS name** (or your Route 53 custom domain if
configured) is the application URL. Also visible in the ECS Console under **sage-prod → sage-ui →
Networking** tab if you attached the load balancer there, and in the target group's associated
listener rule under **EC2 → Load Balancers → sage-ui-alb → Listeners**.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Repository secret AWS_GITHUB_ACTIONS_ROLE_ARN is not set` | Step 9 not done (or was only done under the API guide but the secret didn't save — GitHub secrets are per-repo, so this shouldn't happen if the API guide's Step 11 succeeded). |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub` mismatch — same role as the API, check the API guide's Step 2 trust policy. |
| All targets show `unhealthy` immediately after first healthy deploy in logs | Root route `/` returns a redirect — see the Step 6 health-check caveat. |
| `/sage5` loads but `/api/health` returns 502/504 through the UI domain | `SAGE_API_ORIGIN` wrong, API service down, or `sage-ui-ecs-sg` missing outbound `80` to `sage-api-alb-sg`. Check in that order. |
| Page loads with stale/wrong API origin baked in | `next.config.mjs` reads `SAGE_API_ORIGIN` at build time, not request time — see Step 7's build-arg caveat; you must rebuild, not just update the running task's env var. |
| Browser can't establish HTTPS / cert warning | Using the bare ALB DNS name without a custom domain — see the ACM caveat in Step 6. |

## Rollback

Automatic: circuit breaker (Step 8) rolls back on failed health checks.

Manual:

```bash
aws ecs update-service --cluster sage-prod --service sage-ui \
  --task-definition sage-ui:<previous-revision-number> --region us-east-1
```

---

## Cost and cleanup

Billed continuously: public ALB (~USD 16–20/month) + ACM cert (free) + Fargate tasks (0.5 vCPU /
1 GB × desired count). To remove after a demo:

1. ECS Console → **sage-prod → sage-ui → Delete service**.
2. EC2 Console → delete the `sage-ui` public ALB, its target group, and (if custom domain) the
   Route 53 alias record.
3. ECR Console → delete repository `sage-ui`.
4. Only delete `sage-github-actions-deploy-role` / `sage-ecs-task-execution-role` /
   `sage-ecs-task-role` / the OIDC provider if `sage-api` is also being torn down — they're shared.
5. GitHub → delete the UI-specific variables; leave `AWS_GITHUB_ACTIONS_ROLE_ARN` if the API is
   still deployed.
