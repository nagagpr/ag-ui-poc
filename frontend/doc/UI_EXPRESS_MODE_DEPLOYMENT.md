# `sage-ui` — Deployment on Amazon ECS Express Mode (GitHub Actions → ECR → ECS)

Step-by-step, copy/paste guide for deploying **`sage-ui`** (Next.js, port `3000`, served at
`/sage5`) from `sanumolu-rnt-c/sage-ui` to Amazon ECS Express Mode. Express Mode provisions the
load balancer, HTTPS certificate, target group, security groups, task definition, service, auto
scaling and log group itself. **You do not create an ALB, target group, task definition or ECS
service by hand.**

> **Do [`API_EXPRESS_MODE_DEPLOYMENT.md`](API_EXPRESS_MODE_DEPLOYMENT.md) first.** Its Part A
> creates the IAM roles and cluster that **both services share**, and its Part D gives you the API
> URL this guide needs. This guide adds nothing to IAM — it only verifies the shared setup, creates
> the UI's own ECR repository and GitHub settings, and deploys. After that the two services deploy
> independently: a push to `sage-ui` never touches `sage-api` and vice-versa.

> This guide replaces `UI_GITHUB_ACTIONS_ECS_SETUP.md` (classic model, public ALB + ACM by hand,
> internal API ALB). That file also has a wrong account ID (`107094296439`); the real account is
> **`107094296459`**.

## Values used throughout

| Value | Meaning |
|---|---|
| `107094296459` | AWS account ID |
| `us-east-1` | Region for ECR and ECS |
| `sanumolu-rnt-c` (org ID `313004951`) | GitHub organisation |
| `sanumolu-rnt-c/sage-ui` | UI repository — Dockerfile at repo root, branch `master` **(assumed to be its own repo like `sage-api`; see "If both apps are in one repo" at the end)** |
| `production` | GitHub Actions environment the deploy job runs in (the IAM trust policy is scoped to it) |
| `sage-prod` | ECS cluster — **shared** with `sage-api` |
| `sage-ui` | ECR repository name **and** Express Mode service name |
| `sage-github-actions-deploy-role` | IAM role GitHub Actions assumes via OIDC — **shared**, created/fixed in the API guide |
| `sage-ecs-task-execution-role` | IAM role ECS uses to pull images and write logs — **shared** |
| `sage-ecs-infrastructure-role` | IAM role Express Mode uses to create the ALB, certificate, target groups, security groups — **shared**, created in the API guide A2 |
| `3000` / `/sage5` | Container port / health check path (must return HTTP 200) |
| `SAGE_API_ORIGIN` | `https://<sage-api-endpoint>` from the API guide's Part D — used by `next.config.mjs` to proxy `/api/*` server-side |

## What the pipeline does

```text
git push (master) in sanumolu-rnt-c/sage-ui
      ↓
GitHub Actions: Deploy sage-ui
      ├── assume sage-github-actions-deploy-role via OIDC   (same role as sage-api)
      ├── docker build (Next.js standalone; SAGE_API_ORIGIN passed as build arg)
      ├── push image to ECR   sage-ui:<git-sha>  and  sage-ui:latest
      └── create / update Express Mode service sage-ui in cluster sage-prod
              env: NODE_ENV=production, PORT=3000, HOSTNAME=0.0.0.0, SAGE_API_ORIGIN=https://<sage-api-endpoint>
      ↓
https://<sage-ui-endpoint>/sage5       ← printed in the workflow run summary
      ↓ (server-side Next.js rewrite of /api/*)
https://<sage-api-endpoint>            ← the API's own Express Mode endpoint
```

Both services live in cluster `sage-prod`, in the same VPC/subnets, and **share one Application
Load Balancer** (Express Mode shares an ALB between up to 25 services in the same VPC using
host-header rules). Each service gets its own HTTPS hostname.

---

# Part A — AWS: verify the shared setup, add the UI's own pieces

## A1 — Verify the shared roles exist (created in the API guide, Part A)

All three must print an ARN. If any errors with `NoSuchEntity`, go back to the API guide.

```bash
aws iam get-role --role-name sage-github-actions-deploy-role --query Role.Arn --output text
```

```bash
aws iam get-role --role-name sage-ecs-task-execution-role --query Role.Arn --output text
```

```bash
aws iam get-role --role-name sage-ecs-infrastructure-role --query Role.Arn --output text
```

## A2 — Verify the deploy role's trust policy allows `sage-ui`

```bash
aws iam get-role --role-name sage-github-actions-deploy-role --query "Role.AssumeRolePolicyDocument.Statement[0].Condition.StringLike" --output json
```

The output must contain the two `sage-ui` lines shown below. If it doesn't, apply the API guide's
**A4** (paste the trust policy below over the existing one):

IAM Console → **Roles → `sage-github-actions-deploy-role` → Trust relationships → Edit trust policy**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::107094296459:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": [
            "repo:sanumolu-rnt-c@313004951/sage-api@1379718432:environment:production",
            "repo:sanumolu-rnt-c@313004951/sage-ui@*:environment:production",
            "repo:sanumolu-rnt-c/sage-ui:environment:production"
          ]
        }
      }
    }
  ]
}
```

The two `sage-ui` lines cover both of GitHub's subject-claim formats (with and without the
immutable `@id` suffixes), so it works whether or not the repository uses the new format. To
tighten later: while logged in to GitHub open `https://api.github.com/repos/sanumolu-rnt-c/sage-ui`,
read `"id"`, replace `sage-ui@*` with `sage-ui@<that id>`, and delete the third line.

## A3 — Verify the API is deployed and healthy

The UI needs the API URL. Confirm the API service is running:

```bash
aws ecs describe-services --cluster sage-prod --services sage-api --region us-east-1 --query "services[].{name:serviceName,status:status,running:runningCount}" --output table
```

Expect `ACTIVE` with `running` ≥ 1. Have the API URL from the API guide's Part D ready
(`https://<sage-api-endpoint>`, no trailing slash).

## A4 — ECR repository `sage-ui`

```bash
aws ecr create-repository --repository-name sage-ui --region us-east-1 --image-scanning-configuration scanOnPush=true
```

Console: **ECR → Create repository → Private → name `sage-ui` → Scan on push: Enabled → Create.**

## A5 — Clean-slate check: no classic `sage-ui` service may exist in `sage-prod`

```bash
aws ecs describe-services --cluster sage-prod --services sage-ui --region us-east-1 --query "services[].{name:serviceName,status:status}" --output table
```

- Empty table / `MISSING` → nothing to do.
- `ACTIVE` service that was **not** created by Express Mode (from the old guide) → delete it:

```bash
aws ecs delete-service --cluster sage-prod --service sage-ui --force --region us-east-1
```

If you also created `sage-ui-alb`, `sage-ui-tg` or `sage-ui-*-sg` from the old guide, delete them
in **EC2 → Load Balancers / Target Groups / Security Groups**.

## A6 — Subnets: must match the API

If the API repository has `ECS_SUBNETS` set (API guide A8), the UI repository must use the
**identical** value — Express Mode only shares an ALB between services with the same networking.
If the API left it unset (default VPC), leave it unset here too.

---

# Part B — GitHub configuration: `sanumolu-rnt-c/sage-ui`

**Settings → Secrets and variables → Actions**

**Secrets** tab — create all three (same values as the API repository):

| Secret | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::107094296459:role/sage-github-actions-deploy-role` |
| `ECS_EXECUTION_ROLE_ARN` | `arn:aws:iam::107094296459:role/sage-ecs-task-execution-role` |
| `ECS_INFRASTRUCTURE_ROLE_ARN` | `arn:aws:iam::107094296459:role/sage-ecs-infrastructure-role` |

**Variables** tab:

| Variable | Value |
|---|---|
| `AWS_REGION` | `us-east-1` |
| `ECS_CLUSTER` | `sage-prod` |
| `SAGE_API_ORIGIN` | `https://<sage-api-endpoint>` from the API guide's Part D — **https, no trailing slash** |
| `UI_HEALTH_CHECK_PATH` | optional; default `/sage5`. Set only if `/sage5` does not return HTTP 200 (e.g. `/`) |
| `ECS_SUBNETS` | *(only if the API repository has it — identical value)* |

**Environment:** the job declares `environment: production`. GitHub creates it automatically on
the first run; no protection rules are needed. If your organisation restricts environment creation,
create it once: **Settings → Environments → New environment → `production`**.

---

# Part C — Workflow file: `.github/workflows/deploy-ui.yml`

Replace the whole file with the version below (also saved as
[`workflows/deploy-ui.yml`](workflows/deploy-ui.yml)). It is the working `demo-react-aws`
pipeline plus the UI requirements (port `3000`, `NODE_ENV=production`, `SAGE_API_ORIGIN`,
`/sage5`). If your existing `deploy-ui.yml` has lint/test steps, keep them where the comment says.

```yaml
# sage-ui: GitHub -> Amazon ECR -> Amazon ECS Express Mode
#
#   push -> master     : build (Next.js, inside the Dockerfile), push to ECR, deploy to ECS Express Mode
#   workflow_dispatch  : same as push (manual run from the Actions tab)
#
# Authentication uses GitHub OIDC -> IAM role sage-github-actions-deploy-role (shared with sage-api).
# The job runs in the GitHub environment "production" because the IAM role's trust policy is
# scoped to "...:environment:production" - do NOT remove the `environment:` line below.
#
# Deploy sage-api FIRST. Its workflow summary prints the API URL; put that URL in this repo's
# SAGE_API_ORIGIN variable before running this workflow.
#
# Required repository secrets (Settings -> Secrets and variables -> Actions -> Secrets):
#   AWS_DEPLOY_ROLE_ARN          arn:aws:iam::107094296459:role/sage-github-actions-deploy-role
#   ECS_EXECUTION_ROLE_ARN       arn:aws:iam::107094296459:role/sage-ecs-task-execution-role
#   ECS_INFRASTRUCTURE_ROLE_ARN  arn:aws:iam::107094296459:role/sage-ecs-infrastructure-role
# Repository variables (Variables tab):
#   AWS_REGION            us-east-1
#   ECS_CLUSTER           sage-prod
#   SAGE_API_ORIGIN       https://<sage-api endpoint from its deploy summary>   (https, no trailing slash)
#   UI_HEALTH_CHECK_PATH  (optional) defaults to /sage5 - must return HTTP 200, not a redirect
#   ECS_SUBNETS           (optional) subnet-aaaa,subnet-bbbb - only if the account has no default VPC;
#                         must be the SAME value as in sage-api so both services share one ALB
#
# Setup guide: SAGE_EXPRESS_MODE_DEPLOYMENT.md

name: Deploy sage-ui

on:
  push:
    branches:
      - master
  workflow_dispatch:

permissions:
  id-token: write # request the OIDC token for AWS
  contents: read

env:
  AWS_REGION: ${{ vars.AWS_REGION || 'us-east-1' }}
  ECR_REPOSITORY: sage-ui
  ECS_CLUSTER: ${{ vars.ECS_CLUSTER || 'sage-prod' }}
  ECS_SERVICE: sage-ui

concurrency:
  group: deploy-ui-${{ github.ref }}
  cancel-in-progress: false

jobs:
  deploy:
    name: Build, push, and deploy UI
    runs-on: ubuntu-latest
    environment: production

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      # If your current deploy-ui.yml has lint/test steps (npm ci, npm test ...), keep them here,
      # above "Check required repository secrets". The production build itself runs in the Dockerfile.

      - name: Check required repository secrets and variables
        env:
          DEPLOY_ROLE: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          EXEC_ROLE: ${{ secrets.ECS_EXECUTION_ROLE_ARN }}
          INFRA_ROLE: ${{ secrets.ECS_INFRASTRUCTURE_ROLE_ARN }}
          API_ORIGIN: ${{ vars.SAGE_API_ORIGIN }}
        run: |
          missing=0
          [ -z "$DEPLOY_ROLE" ] && { echo "::error::Repository secret AWS_DEPLOY_ROLE_ARN is not set"; missing=1; }
          [ -z "$EXEC_ROLE" ]   && { echo "::error::Repository secret ECS_EXECUTION_ROLE_ARN is not set"; missing=1; }
          [ -z "$INFRA_ROLE" ]  && { echo "::error::Repository secret ECS_INFRASTRUCTURE_ROLE_ARN is not set"; missing=1; }
          case "$INFRA_ROLE" in
            *sage-ecs-task-role|*sage-ecs-task-execution-role)
              echo "::error::ECS_INFRASTRUCTURE_ROLE_ARN must be sage-ecs-infrastructure-role (trusts ecs.amazonaws.com), not a task role"
              missing=1 ;;
          esac
          if [ -z "$API_ORIGIN" ]; then
            echo "::error::Repository variable SAGE_API_ORIGIN is not set. Deploy sage-api first and copy the API URL from that run's summary."
            missing=1
          else
            case "$API_ORIGIN" in
              https://*) ;;
              *) echo "::error::SAGE_API_ORIGIN must start with https:// (Express Mode endpoints are HTTPS-only)"; missing=1 ;;
            esac
            case "$API_ORIGIN" in
              */) echo "::error::SAGE_API_ORIGIN must not end with a trailing slash"; missing=1 ;;
            esac
          fi
          if [ "$missing" = 1 ]; then
            echo "::error::Follow SAGE_EXPRESS_MODE_DEPLOYMENT.md Part B, then re-run this workflow."
            exit 1
          fi

      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          role-session-name: github-actions-sage-ui
          aws-region: ${{ env.AWS_REGION }}

      - name: Log in to Amazon ECR
        id: ecr-login
        uses: aws-actions/amazon-ecr-login@v2

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: ./Dockerfile
          push: true
          provenance: false # plain image manifest; avoids untagged attestation artifacts in ECR
          # SAGE_API_ORIGIN is passed at BUILD time too, in case next.config.mjs reads it at the
          # top level (evaluated during `next build`). Harmless if only the runtime value is used.
          build-args: |
            SAGE_API_ORIGIN=${{ vars.SAGE_API_ORIGIN }}
          tags: |
            ${{ steps.ecr-login.outputs.registry }}/${{ env.ECR_REPOSITORY }}:${{ github.sha }}
            ${{ steps.ecr-login.outputs.registry }}/${{ env.ECR_REPOSITORY }}:latest
          cache-from: type=gha,scope=sage-ui
          cache-to: type=gha,mode=max,scope=sage-ui

      # Express Mode creates/updates everything: task definition, service, ALB + HTTPS listener,
      # target group, security groups, auto scaling, log group. No task-definition JSON needed.
      - name: Deploy to Amazon ECS Express Mode
        id: deploy
        uses: aws-actions/amazon-ecs-deploy-express-service@v1
        with:
          cluster: ${{ env.ECS_CLUSTER }}
          service-name: ${{ env.ECS_SERVICE }}
          image: ${{ steps.ecr-login.outputs.registry }}/${{ env.ECR_REPOSITORY }}:${{ github.sha }}
          execution-role-arn: ${{ secrets.ECS_EXECUTION_ROLE_ARN }}
          infrastructure-role-arn: ${{ secrets.ECS_INFRASTRUCTURE_ROLE_ARN }}
          container-port: 3000
          health-check-path: ${{ vars.UI_HEALTH_CHECK_PATH || '/sage5' }}
          environment-variables: '[{"name":"NODE_ENV","value":"production"},{"name":"PORT","value":"3000"},{"name":"HOSTNAME","value":"0.0.0.0"},{"name":"SAGE_API_ORIGIN","value":"${{ vars.SAGE_API_ORIGIN }}"}]'
          # Optional: comma-separated PUBLIC subnet IDs (>= 2 AZs, same VPC). Set repository
          # variable ECS_SUBNETS only if the account has no default VPC; leave unset otherwise.
          subnets: ${{ vars.ECS_SUBNETS }}
          cpu: 512 # 0.5 vCPU
          memory: 1024 # 1 GB
          min-task-count: 1
          max-task-count: 2

      - name: Deployment summary
        run: |
          EP="${{ steps.deploy.outputs.endpoint }}"; EP="${EP#https://}"; EP="${EP#http://}"; EP="${EP%/}"
          {
            echo "### Deployed sage-ui to Amazon ECS Express Mode :rocket:"
            echo ""
            echo "- **Service ARN:** ${{ steps.deploy.outputs.service-arn }}"
            echo "- **UI URL:** https://$EP/sage5"
            echo "- **API origin used:** ${{ vars.SAGE_API_ORIGIN }}"
            echo "- **Image tag:** ${{ github.sha }}"
          } >> "$GITHUB_STEP_SUMMARY"
```

---

# Part D — Deploy

1. Make sure `SAGE_API_ORIGIN` is set (Part B) — the workflow refuses to run without it.
2. Push to `master`, or **Actions → Deploy sage-ui → Run workflow**.
3. First run: **3–10 minutes** (fast if the API already created the shared ALB; longer only if
   Express Mode has to provision a new one). Later runs take 3–4 minutes.
4. Open the run → **Summary** → the **UI URL** is `https://<sage-ui-endpoint>/sage5`.

From then on, every push to `master` redeploys the UI only. If the API URL ever changes (the
`sage-api` service was deleted and recreated), update `SAGE_API_ORIGIN` and re-run this workflow —
the value is applied both as a Docker build arg and as a runtime environment variable, so one
re-run covers both cases.

---

# Part E — Verification

**Browser:** `https://<sage-ui-endpoint>/sage5` loads the app and its API-backed screens work.

**ECS state (both services):**

```bash
aws ecs describe-services --cluster sage-prod --services sage-api sage-ui --region us-east-1 --query "services[].{name:serviceName,status:status,running:runningCount,desired:desiredCount}" --output table
```

**Logs:** CloudWatch → Log groups → `/aws/ecs/sage-prod/sage-ui-…` (Express Mode creates it), or
**ECS → Clusters → sage-prod → Services → sage-ui → Logs / Health and metrics**.

**Target health (if unhealthy):** **EC2 → Target Groups** → the group tagged `AmazonECSManaged`
for `sage-ui` → **Targets** tab.

**Shared ALB check (optional):** **EC2 → Load Balancers** → one ALB tagged `AmazonECSManaged`
whose HTTPS listener has host-header rules for both `sage-api` and `sage-ui`.

---

# Troubleshooting

| Symptom (Actions log) | Cause / fix |
|---|---|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | The trust policy lacks the `sage-ui` lines (A2), or the job doesn't have `environment: production`. |
| `iam:PassRole … not authorized` | The API guide's A3 policy is not in place, or `ECS_INFRASTRUCTURE_ROLE_ARN` points at a task role instead of `sage-ecs-infrastructure-role`. |
| `AccessDeniedException … ecs:CreateExpressGatewayService` | API guide A3 not applied. |
| `Repository variable SAGE_API_ORIGIN is not set` / `must start with https://` / `trailing slash` | Part B — set it exactly as `https://<sage-api-endpoint>` with no `/` at the end. |
| Service `sage-ui` already exists / `InvalidParameterException` on create | A classic service with that name exists. A5. |
| Subnet / VPC errors, or the UI gets its **own** ALB instead of sharing | `ECS_SUBNETS` differs from the API repository's value (A6). |
| Deployment never becomes healthy; tasks restart | The health path must return **HTTP 200**. If `/sage5` redirects (e.g. to `/sage5/`), set `UI_HEALTH_CHECK_PATH` to a path that returns 200. The app must bind `0.0.0.0:3000` (`HOSTNAME=0.0.0.0` is set for that). Read the CloudWatch log group first. |
| `CannotPullContainerError` | Image tag not in ECR (build step failed) or `sage-ecs-task-execution-role` lacks `AmazonECSTaskExecutionRolePolicy`. |
| UI loads but API calls fail (502 / network error) | `SAGE_API_ORIGIN` wrong or the API service is unhealthy (`curl https://<sage-api-endpoint>/api/health`). Fix and re-run **Deploy sage-ui**. |
| `Unable to assume the service linked role` | First ECS/ELB/auto-scaling use in the account. Re-run the workflow. |
| `Repository secret … is not set` | Part B not finished. |

---

# Cost and cleanup

Express Mode is free; the resources it creates are billed: the Application Load Balancer
(≈ USD 16–20/month, **shared** with `sage-api`) and one Fargate task at 0.5 vCPU / 1 GB
(≈ USD 18/month at `min-task-count: 1`). Check current pricing before leaving it running.

To remove **everything** after the POC (both services):

1. **ECS → Clusters → sage-prod → Services** → delete `sage-ui`, then `sage-api` (Express Mode
   deprovisions the shared ALB and certificate when no service uses them any more).
2. **ECR** → delete repositories `sage-ui`, `sage-api` (optional; removes images).
3. **IAM → Roles** → delete `sage-ecs-infrastructure-role`, `sage-github-actions-deploy-role`,
   `sage-ecs-task-role`, `sage-ecs-task-execution-role` (only if nothing else uses them).
4. GitHub → both repositories → delete the secrets and variables.

---

# Notes

- **Both endpoints are public HTTPS.** That was the accepted POC trade-off. Do **not** lock the
  shared ALB's security group to an office IP — `sage-ui`'s server-side calls to the API go through
  that same ALB and would be blocked too.
- **Going to production later:** keep `sage-ui` on public subnets; give `sage-api` two **private**
  subnet IDs so Express Mode creates an internal ALB for it (see the API guide's Notes). Both must
  stay in the same VPC.
- **If both apps are in one repository** instead of two: keep both workflows in that repo, add
  `paths:` filters (`sage-ui/**` + the workflow file for this one), set `context: sage-ui` and
  `file: sage-ui/Dockerfile` in the build step, and only that repository's `sub` entry is needed
  in the trust policy.

References: [Resources created by Amazon ECS Express Mode](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html) ·
[aws-actions/amazon-ecs-deploy-express-service](https://github.com/aws-actions/amazon-ecs-deploy-express-service) ·
[GitHub immutable OIDC subject claims](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)
