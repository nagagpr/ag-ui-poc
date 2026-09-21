# GitHub Actions → Amazon ECR → Amazon ECS: `sage-api` Deployment Setup

One-time setup + repeatable deployment guide for the `sage-api` FastAPI service, deployed via
GitHub Actions → Amazon ECR → Amazon ECS (Fargate, classic task-definition/service model).

> **Adapted from, not copied from, [`GITHUB_ACTIONS_ECS_SETUP.md`](GITHUB_ACTIONS_ECS_SETUP.md).**
> That proven pipeline uses **ECS Express Mode**, which auto-provisions a single ALB for one
> public service. `sage-api` must sit behind an **internal-only** ALB (it is not meant to be
> public — see [`SAGE_API_AWS_DEPLOYMENT.md`](SAGE_API_AWS_DEPLOYMENT.md) §2) and shares an ECS
> cluster with `sage-ui`. Express Mode cannot create an internal ALB or attach a service to an
> existing cluster, so this guide uses classic ECS **task definitions + services**, while reusing
> the baseline's proven OIDC-role / no-stored-keys IAM pattern and its GitHub secrets flow.

> ⚠️ **This session could not read the actual `sage-api` source, Dockerfile, or
> `.github/workflows/deploy-api.yml`** (the repository lives in a location this session has no
> access to). Every value below is either carried over from `SAGE_API_AWS_DEPLOYMENT.md` (already
> decided, cited inline) or marked **`VERIFY/REQUIRED`** where it must be confirmed against the
> real repository before you run this for the first time. Do not treat a `VERIFY/REQUIRED` item as
> already true.

## What the pipeline does

```text
git push (main, paths: sage-api/**)
      ↓
GitHub Actions (deploy-api.yml)
      ├── assume IAM role via OIDC          (no AWS access keys stored anywhere)
      ├── docker build sage-api/            (with JFrog build args, if required)
      ├── push image to Amazon ECR          sage-api:<git-sha>  and  sage-api:latest
      ├── register new ECS task definition revision (family: sage-api)
      └── update ECS service sage-api on cluster sage-prod, wait for stability
      ↓
Internal ALB target group (port 8000, health path /api/health) → sage-api Fargate tasks
      ↓
Reachable only from sage-ui's ECS security group (and anything else inside the VPC you allow)
```

There is **no public URL for the API by itself**. Its "application URL" is the internal ALB DNS
name, consumed by `sage-ui` as `SAGE_API_ORIGIN`. Verification of the end-to-end app happens
through the UI's public URL — see [`UI_GITHUB_ACTIONS_ECS_SETUP.md`](UI_GITHUB_ACTIONS_ECS_SETUP.md).

## Values used throughout

| Placeholder / value | Meaning | Source |
|---|---|---|
| `107094296439` | AWS Account ID (`QEAI.DEV`) | `SAGE_API_AWS_DEPLOYMENT.md` §0 |
| `us-east-1` | Region for ECR, ECS, ALB | `SAGE_API_AWS_DEPLOYMENT.md` §0 |
| `sage-api` | ECR repo name, ECS task-def family, ECS service name, container name | `SAGE_API_AWS_DEPLOYMENT.md` §4 |
| `sage-prod` | Shared ECS cluster (also hosts `sage-ui`) | `SAGE_API_AWS_DEPLOYMENT.md` §4 |
| `sage-github-actions-deploy-role` | IAM role GitHub Actions assumes via OIDC — **shared with `sage-ui`'s workflow**, same repo | `SAGE_API_AWS_DEPLOYMENT.md` §8 secret value |
| `sage-ecs-task-execution-role` | ECS task execution role (pulls image, writes logs) | `SAGE_API_AWS_DEPLOYMENT.md` §6 |
| `sage-ecs-task-role` | ECS task role (app-level AWS permissions, if any) | `SAGE_API_AWS_DEPLOYMENT.md` §6 |
| `<GITHUB_ORG>/<REPO_NAME>` | GitHub org/user and repository name | **VERIFY/REQUIRED** — not stated in either source doc |
| `8000` | Container port | `SAGE_API_AWS_DEPLOYMENT.md` §1 |
| `/api/health` | Health check path | `SAGE_API_AWS_DEPLOYMENT.md` §4 |
| `sage-api/Dockerfile` | Dockerfile location | `SAGE_API_AWS_DEPLOYMENT.md` §1 — **VERIFY/REQUIRED**, file not read |
| `.github/workflows/deploy-api.yml` | Workflow file path | `SAGE_API_AWS_DEPLOYMENT.md` §1 — **VERIFY/REQUIRED**, file not read |

## Prerequisites

- AWS account `107094296439`, region `us-east-1`, admin access to IAM/ECR/ECS/EC2/CloudWatch.
- The GitHub repository containing `sage-api/` pushed to `main` — **VERIFY/REQUIRED**: confirm the
  org/repo name and that `sage-api/` and `sage-ui/` really live in the *same* repo (both source
  docs assume a shared `AWS_GITHUB_ACTIONS_ROLE_ARN` secret, which only makes sense for one repo).
- A VPC with at least two **private** subnets (API tasks + internal ALB must not be internet
  routable) across two Availability Zones, and NAT Gateway or VPC endpoints for ECR/CloudWatch
  Logs/JFrog reachability from those private subnets. **VERIFY/REQUIRED**: get the actual VPC ID
  and private subnet IDs from your account — no default VPC has private subnets, so this cannot be
  "the default VPC" the way the baseline doc's Express Mode setup could assume.
- Confirm whether `sage-api` needs a database or other AWS resource. `SAGE_API_AWS_DEPLOYMENT.md`
  lists only "Secrets Manager or SSM Parameter Store entries for future application secrets, if
  needed" and no RDS/DynamoDB/ElastiCache resource. **VERIFY/REQUIRED**: inspect
  `sage-api/app/main.py` / its settings module for a DB connection string or ORM before assuming
  there is none — if one exists, add its provisioning as a step before Step 8 below.
- Decide whether JFrog requires authentication (§3 below) before running the pipeline for real —
  an unauthenticated `PIP_INDEX_URL` will fail mid-build if the mirror requires a token.

---

> **Account status confirmed 2026-09-21**: account `107094296439` currently has **none** of the
> resources in Steps 1–3 below — no OIDC provider, no `sage-github-actions-deploy-role`, no
> `sage-ecs-task-execution-role`, no `sage-ecs-task-role`. Create all of them now, in order. They
> are account-wide (not per-service), shared with `sage-ui`'s deployment — if you do this API
> guide first, `sage-ui`'s Steps 1–3 will already be satisfied when you get to it; just don't
> create any of them a second time.

## Step 1 — Add GitHub as an OIDC identity provider

IAM Console → **Identity providers** → **Add provider**:

| Field | Value |
|---|---|
| Provider type | **OpenID Connect** |
| Provider URL | `https://token.actions.githubusercontent.com` |
| Audience | `sts.amazonaws.com` |

Click **Add provider**. This is a one-time, account-level resource shared by both services'
GitHub Actions workflows.

Or via CLI (fetches the current TLS thumbprint dynamically rather than hardcoding one, since
GitHub rotates it periodically):

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list $(echo | openssl s_client -servername token.actions.githubusercontent.com -showcerts -connect token.actions.githubusercontent.com:443 2>/dev/null | openssl x509 -fingerprint -sha1 -noout | cut -d= -f2 | tr -d ':') \
  --region us-east-1
```

---

## Step 2 — IAM role: `sage-github-actions-deploy-role` (assumed by GitHub Actions)

This role is **shared** by both `deploy-api.yml` and `deploy-ui.yml` (both source docs use the
identical `AWS_GITHUB_ACTIONS_ROLE_ARN` secret value) — create it once here.

IAM Console → **Roles** → **Create role**:

1. Trusted entity type: **Web identity**
2. Identity provider: `token.actions.githubusercontent.com` — Audience: `sts.amazonaws.com`
3. GitHub organization / repository / branch: fill with your **VERIFY/REQUIRED** `<GITHUB_ORG>`,
   `<REPO_NAME>`, `main`
4. **Next** → Add permissions: leave everything unticked → **Next**
5. Role name: `sage-github-actions-deploy-role` → **Create role**
6. Open the role → **Permissions** → **Add permissions ▾ → Create inline policy** → **JSON** →
   paste (replace `<AWS_ACCOUNT_ID>` with `107094296439` everywhere) → policy name
   `deploy-sage-services`:

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
        "arn:aws:ecr:us-east-1:<AWS_ACCOUNT_ID>:repository/sage-api",
        "arn:aws:ecr:us-east-1:<AWS_ACCOUNT_ID>:repository/sage-ui"
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
        "arn:aws:iam::<AWS_ACCOUNT_ID>:role/sage-ecs-task-execution-role",
        "arn:aws:iam::<AWS_ACCOUNT_ID>:role/sage-ecs-task-role"
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

> Note on `ecs:RegisterTaskDefinition` / `ecs:DescribeServices` using `Resource: "*"`: ECS task
> definitions and the `DescribeTaskDefinition`/`RegisterTaskDefinition` actions do not support
> resource-level restriction to a specific family in IAM; scoping is effectively done by which
> task-definition family the workflow itself is coded to touch. If your security policy requires
> tighter scoping, add a `Condition` on `ecs:cluster`/`ecs:service` ARNs for `UpdateService`
> instead of leaving this as a follow-up **VERIFY/REQUIRED** hardening item.

Trust policy (the wizard writes this from step 3 above — confirm it matches):

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

---

## Step 3 — IAM role: `sage-ecs-task-execution-role`

Does not exist yet in this account — create it now. IAM Console → **Roles** → **Create role** →
Trusted entity: **Custom trust policy** → paste:

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

If `sage-api` needs to read Secrets Manager/SSM values at container start (see Prerequisites),
add an inline policy here for `secretsmanager:GetSecretValue` / `ssm:GetParameters` scoped to the
specific secret/parameter ARNs — **VERIFY/REQUIRED** depending on the DB/secrets check above.

## Step 4 — IAM role: `sage-ecs-task-role`

Also does not exist yet — create it now. Same trust policy as Step 3. Role name
`sage-ecs-task-role`. Attach **no managed policies** at creation time — this role has zero
permissions until proven otherwise. Add inline permissions only if `sage-api`'s own code calls an
AWS SDK at runtime (e.g., S3, DynamoDB) — **VERIFY/REQUIRED**, not established in the source docs.
This is the role the *application code* runs as; the execution role in Step 3 is only used by the
ECS agent to pull the image and ship logs — the two are never interchangeable.

CLI equivalent for both roles:

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

## Step 5 — Create the ECR repository

AWS Console → **ECR** → **Create repository**:

| Field | Value |
|---|---|
| Visibility | Private |
| Name | `sage-api` |
| Scan on push | Enabled |

Resulting image URI: `107094296439.dkr.ecr.us-east-1.amazonaws.com/sage-api`

Or via CLI:

```bash
aws ecr create-repository --repository-name sage-api --region us-east-1 --image-scanning-configuration scanOnPush=true
```

---

## Step 6 — Create the CloudWatch log group

```bash
aws logs create-log-group --log-group-name /ecs/sage-api --region us-east-1
```

Or Console: **CloudWatch → Logs → Log groups → Create log group** → `/ecs/sage-api`.

---

## Step 7 — Networking: internal ALB, target group, security groups

**VERIFY/REQUIRED**: substitute your actual VPC ID and private subnet IDs everywhere below —
none of these exist yet in this environment as far as this session can confirm.

1. **Security group `sage-api-alb-sg`** (attached to the internal ALB):
   - Inbound: TCP `80` from `sage-ui-ecs-sg` (created in the UI guide's Step 7) — not `0.0.0.0/0`,
     this ALB is internal.
   - Outbound: TCP `8000` to `sage-api-ecs-sg`.
2. **Security group `sage-api-ecs-sg`** (attached to the `sage-api` ECS service):
   - Inbound: TCP `8000` from `sage-api-alb-sg`.
   - Outbound: TCP `443` to `0.0.0.0/0` (ECR, CloudWatch Logs, JFrog) — restrict to VPC endpoint
     security groups instead if you use PrivateLink/VPC endpoints.
3. **Internal ALB**: EC2 Console → **Load Balancers → Create Application Load Balancer**:
   - Scheme: **Internal**
   - Subnets: your two **private** subnets — `<PRIVATE_SUBNET_ID_1>`, `<PRIVATE_SUBNET_ID_2>`
   - Security group: `sage-api-alb-sg`
   - Listener: HTTP `80` (no ACM cert needed — internal, VPC-only traffic)
4. **Target group `sage-api-tg`**:
   - Type: **IP**
   - Protocol/port: HTTP `8000`
   - Health check path: `/api/health`
   - Healthy threshold `2`, unhealthy threshold `3`
5. Record the ALB's DNS name (EC2 → Load Balancers → `sage-api-alb` → DNS name column) — this is
   the value you will give `sage-ui` as `SAGE_API_ORIGIN` in the UI guide's Step 9.

---

## Step 8 — ECS task definition (family `sage-api`)

Console path: **ECS → Task definitions → Create new task definition** — or register directly with
this JSON (adjust the execution/task role ARNs and log region if they differ):

```json
{
  "family": "sage-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::107094296439:role/sage-ecs-task-execution-role",
  "taskRoleArn": "arn:aws:iam::107094296439:role/sage-ecs-task-role",
  "containerDefinitions": [
    {
      "name": "sage-api",
      "image": "107094296439.dkr.ecr.us-east-1.amazonaws.com/sage-api:latest",
      "essential": true,
      "portMappings": [{ "containerPort": 8000, "protocol": "tcp" }],
      "environment": [
        { "name": "PORT", "value": "8000" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/sage-api",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

```bash
aws ecs register-task-definition --cli-input-json file://sage-api-task-def.json --region us-east-1
```

**VERIFY/REQUIRED**: the `environment` block only contains `PORT`, which is all
`SAGE_API_AWS_DEPLOYMENT.md` §6 lists. If the API needs a database URL, secrets, or a JFrog runtime
dependency, add those here (as `environment` entries or `secrets` entries referencing Secrets
Manager/SSM ARNs) before first deployment — do not assume `PORT` alone is sufficient without
checking `sage-api`'s actual config/settings module.

---

## Step 9 — ECS service `sage-api`

Console: **ECS → cluster `sage-prod` → Create service** (create the cluster first if it doesn't
exist: **ECS → Clusters → Create cluster**, name `sage-prod`, infrastructure: **AWS Fargate**).

| Field | Value |
|---|---|
| Launch type | Fargate |
| Task definition family | `sage-api` |
| Service name | `sage-api` |
| Desired tasks | `2` (prod) / `1` (lower envs) |
| Subnets | your **private** subnets |
| Public IP | Disabled |
| Security group | `sage-api-ecs-sg` |
| Load balancer | internal ALB from Step 7 → target group `sage-api-tg` on port `8000` |
| Deployment | Enable circuit breaker + rollback; health check grace period `60`s |

CLI equivalent, once the ALB/target group ARNs are known:

```bash
aws ecs create-service \
  --cluster sage-prod \
  --service-name sage-api \
  --task-definition sage-api \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<PRIVATE_SUBNET_ID_1>,<PRIVATE_SUBNET_ID_2>],securityGroups=[<sage-api-ecs-sg-id>],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=<sage-api-tg-arn>,containerName=sage-api,containerPort=8000" \
  --health-check-grace-period-seconds 60 \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}" \
  --region us-east-1
```

---

## Step 10 — JFrog build arguments (only if the PyPI mirror needs them)

`SAGE_API_AWS_DEPLOYMENT.md` §3 states the Dockerfile accepts `PIP_INDEX_URL` and
`PIP_TRUSTED_HOST` build args. **VERIFY/REQUIRED**: open `sage-api/Dockerfile` and confirm it
actually has `ARG PIP_INDEX_URL` / `ARG PIP_TRUSTED_HOST` and a `pip install --index-url
$PIP_INDEX_URL --trusted-host $PIP_TRUSTED_HOST` line — if it doesn't, the build args in Step 13's
workflow do nothing and the build will hit public PyPI regardless.

If your mirror requires authentication, do **not** put the credentialed URL in a GitHub *variable*
(variables are visible in logs and to anyone with read access to the repo). Store it as a
**secret** named `PIP_INDEX_URL` instead, and update the workflow to read
`${{ secrets.PIP_INDEX_URL }}` in that one step only.

---

## Step 11 — GitHub repository secrets

GitHub → `<GITHUB_ORG>/<REPO_NAME>` → **Settings → Secrets and variables → Actions → Secrets →
New repository secret**:

| Secret name | Value |
|---|---|
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | `arn:aws:iam::107094296439:role/sage-github-actions-deploy-role` |

(If JFrog needs auth per Step 10, also add secret `PIP_INDEX_URL` here with the authenticated URL.)

## Step 12 — GitHub repository variables

Same page, **Variables** tab → **New repository variable**:

| Variable name | Value |
|---|---|
| `AWS_REGION` | `us-east-1` |
| `ECS_CLUSTER` | `sage-prod` |
| `ECS_API_SERVICE` | `sage-api` |
| `ECS_API_TASK_DEFINITION` | `sage-api` |
| `PIP_INDEX_URL` | `https://rnt.jfrog.io/artifactory/api/pypi/pypi-org-remote/simple` (omit if using the secret instead) |
| `PIP_TRUSTED_HOST` | `rnt.jfrog.io` |

---

## Step 13 — Workflow file: `.github/workflows/deploy-api.yml`

**VERIFY/REQUIRED**: this file's existence and exact contents were not readable this session.
The YAML below is what §8 of `SAGE_API_AWS_DEPLOYMENT.md` describes the trigger/secrets/variables
for — reconcile it against whatever is actually committed before relying on it.

```yaml
name: Deploy sage-api

on:
  push:
    branches: [main]
    paths:
      - "sage-api/**"
      - ".github/workflows/deploy-api.yml"
  workflow_dispatch: {}

permissions:
  id-token: write
  contents: read

env:
  AWS_REGION: ${{ vars.AWS_REGION }}
  ECR_REPOSITORY: sage-api
  ECS_CLUSTER: ${{ vars.ECS_CLUSTER }}
  ECS_SERVICE: ${{ vars.ECS_API_SERVICE }}
  ECS_TASK_DEFINITION_FAMILY: ${{ vars.ECS_API_TASK_DEFINITION }}
  CONTAINER_NAME: sage-api

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
            --build-arg PIP_INDEX_URL="${{ secrets.PIP_INDEX_URL || vars.PIP_INDEX_URL }}" \
            --build-arg PIP_TRUSTED_HOST="${{ vars.PIP_TRUSTED_HOST }}" \
            -t "$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" \
            -t "$ECR_REGISTRY/$ECR_REPOSITORY:latest" \
            sage-api
          docker push "$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG"
          docker push "$ECR_REGISTRY/$ECR_REPOSITORY:latest"
          echo "image=$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" >> "$GITHUB_OUTPUT"

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

**First-time setup (once per AWS account/environment)** — Steps 1–9 above: OIDC provider, both
IAM roles, ECR repo, log group, networking (ALB/target group/security groups), initial task
definition registration, and initial `ecs create-service`. Steps 11–13 (secrets/variables/workflow
file) are also one-time, done in GitHub.

**Normal deployment (every subsequent change)** — just `git push` to `main` with changes under
`sage-api/**`, or **Actions → Deploy sage-api → Run workflow**. The workflow builds, pushes a new
image tag, registers a new task-definition revision, and updates the existing service — no console
steps required.

---

## Health checks

- Container-level expectation: `GET /api/health` on port `8000` returns HTTP 200 with a body like:

```json
{
  "status": "ok",
  "success": true,
  "data": { "status": "ok", "service": "sage-api", "version": "5.1.0" },
  "traceId": null
}
```

  (`SAGE_API_AWS_DEPLOYMENT.md` §10 — **VERIFY/REQUIRED** against the actual handler in
  `sage-api/app/main.py` or its router module; the version string will drift over time.)
- Target group health check: path `/api/health`, healthy threshold `2`, unhealthy threshold `3`,
  ECS service health-check grace period `60`s (Step 7/9 above).
- If tasks start but the target group never turns healthy, check in this order: container logs in
  CloudWatch (`/ecs/sage-api`) for a crash/bind error → security group `sage-api-alb-sg` outbound
  to `sage-api-ecs-sg` on `8000` → security group `sage-api-ecs-sg` inbound from `sage-api-alb-sg`
  on `8000` → whether the app actually binds `0.0.0.0:8000` (not `127.0.0.1`).

## Networking / security-group requirements (summary)

See Step 7. In short: `sage-api-alb-sg` only accepts from `sage-ui-ecs-sg`; `sage-api-ecs-sg` only
accepts from `sage-api-alb-sg`; both ALB and tasks live in private subnets with no public IP.

## Load balancer / HTTPS

No HTTPS/ACM certificate for the API — it is internal HTTP-only by design
(`SAGE_API_AWS_DEPLOYMENT.md` §2: "The API should not be publicly exposed"). If a future
requirement makes the API directly internet-facing, that changes this guide substantially
(needs its own ACM cert, public subnets, and CORS handling) — don't make that change without
confirming the requirement first.

## CORS

Not required for the primary production path: the browser only ever talks to `sage-ui` (same
origin), and `sage-ui`'s Next.js server does the `/api/*` rewrite to `SAGE_API_ORIGIN` server-side
— server-to-server calls aren't subject to browser CORS. **VERIFY/REQUIRED**: if
`NEXT_PUBLIC_SAGE_API_BASE_URL` (mentioned in `SAGE_UI_AWS_DEPLOYMENT.md` §2) is ever set to make
the browser call the API origin directly, `sage-api` will need CORS middleware allowing the UI's
public origin — check `sage-api/app/main.py` for `CORSMiddleware` before enabling that variable.

---

## Verification / testing steps

1. GitHub → **Actions** → `Deploy sage-api` run → confirm green checkmark on all steps.
2. AWS Console → **ECR → sage-api** → confirm an image tag matching the triggering commit SHA.
3. AWS Console → **ECS → sage-prod → sage-api** → **Deployments** tab → confirm the new task
   definition revision is `PRIMARY` and `Running count == Desired count`.
4. AWS Console → **EC2 → Target Groups → sage-api-tg** → **Targets** tab → all targets `healthy`.
5. From an instance/task inside the VPC (or via ECS Exec into a running task):
   `curl -s http://<internal-alb-dns-name>/api/health` → expect the JSON in "Health checks" above.
6. Only after `sage-ui` is deployed and pointed at this ALB: verify end-to-end via the UI's public
   URL as described in [`UI_GITHUB_ACTIONS_ECS_SETUP.md`](UI_GITHUB_ACTIONS_ECS_SETUP.md).

## How to check GitHub Actions logs

GitHub → repository → **Actions** tab → select the `Deploy sage-api` workflow → click the run →
click the `deploy` job → expand each step. The "Build and push image" step shows the Docker build
output (JFrog pip resolution errors surface here); the final "Deploy to ECS" step shows
service-stability polling output and fails loudly with the ECS deployment failure reason if the
circuit breaker trips.

## How to check ECS task/service logs in CloudWatch

AWS Console → **CloudWatch → Logs → Log groups → `/ecs/sage-api`** → open the newest log stream
(named `ecs/sage-api/<task-id>`) → this is stdout/stderr from the `uvicorn` process. Application
startup errors, unhandled exceptions per request, and bind failures all appear here first — check
this before the target-group health-check symptom, since a crashing container will fail health
checks as a downstream effect.

## How to verify the final application URL

The API has no end-user URL. Confirm its internal ALB DNS name (EC2 → Load Balancers →
`sage-api-alb` → **DNS name** column) matches exactly what is set as `SAGE_API_ORIGIN` in the
`sage-ui` GitHub variable — a mismatch here is the most common cause of the UI showing "migration
gap" errors for endpoints that are actually implemented.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Repository secret AWS_GITHUB_ACTIONS_ROLE_ARN is not set` | Step 11 not done. Add it, re-run. |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub` doesn't match `repo:<GITHUB_ORG>/<REPO_NAME>:ref:refs/heads/main`, or the branch that ran the workflow isn't `main`. |
| `RepositoryNotFoundException` on push | ECR repo `sage-api` doesn't exist in `us-east-1` (Step 5). |
| `iam:PassRole ... is not authorized` | Step 2 policy's `PassEcsRoles` resource ARNs have the wrong account ID or role name. |
| Build fails resolving Python packages | JFrog `PIP_INDEX_URL`/`PIP_TRUSTED_HOST` wrong, unreachable from GitHub-hosted runners (this build runs on GitHub's network, not inside your VPC — if JFrog is only reachable from your VPC, the build must instead run on a self-hosted runner inside the VPC — **VERIFY/REQUIRED**, check whether `rnt.jfrog.io` is publicly reachable). |
| Task starts then stops repeatedly | Check CloudWatch `/ecs/sage-api` for the crash reason; also check ECS **Service → Tasks → \[task] → Stopped reason** for out-of-memory (`OutOfMemoryError: Container killed`) vs application exception. |
| Target group targets stay `unhealthy` | Confirm app binds `0.0.0.0:8000` not `localhost`; confirm `sage-api-ecs-sg` allows inbound `8000` from `sage-api-alb-sg`; confirm `/api/health` returns 200 without auth. |
| UI reports "migration gap" for an endpoint that should exist | `SAGE_API_ORIGIN` on the UI side doesn't match this API's ALB DNS name, or the ALB target group is pointing at the wrong port/health path. |

## Rollback

Automatic: ECS deployment circuit breaker (enabled in Step 9) rolls back to the previous task
definition revision if new tasks fail to start or fail health checks — no action needed.

Manual: AWS Console → **ECS → sage-prod → sage-api → Update service** → under task definition,
select the previous healthy revision number → **Update** → wait for `Deployments` to show the
older revision as `PRIMARY` and stable. Or via CLI:

```bash
aws ecs update-service --cluster sage-prod --service sage-api \
  --task-definition sage-api:<previous-revision-number> --region us-east-1
```

---

## Cost and cleanup

Billed continuously once created: the internal ALB (~USD 16–20/month) and Fargate tasks (0.5 vCPU
/ 1 GB × desired count, per Step 8). To remove after a demo/POC:

1. ECS Console → **sage-prod → sage-api → Delete service**.
2. EC2 Console → delete the `sage-api` internal ALB and its target group.
3. ECR Console → delete repository `sage-api` (optional — removes stored images).
4. Delete `sage-ecs-task-role` if nothing else uses it; keep `sage-ecs-task-execution-role` and
   `sage-github-actions-deploy-role` if `sage-ui` still uses them.
5. GitHub → delete the `AWS_GITHUB_ACTIONS_ROLE_ARN` secret and the API-specific variables only if
   `sage-ui`'s workflow doesn't also need them (it needs the same role secret — do not delete it
   if the UI is still deployed).
