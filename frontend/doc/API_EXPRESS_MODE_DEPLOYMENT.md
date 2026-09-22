# `sage-api` — Deployment on Amazon ECS Express Mode (GitHub Actions → ECR → ECS)

Step-by-step, copy/paste guide for deploying **`sage-api`** (FastAPI, port `8000`) from
`sanumolu-rnt-c/sage-api` to Amazon ECS Express Mode — the same pipeline that already works for
`sanumolu-rnt-c/demo-react-aws`. Express Mode provisions the load balancer, HTTPS certificate,
target group, security groups, task definition, service, auto scaling and log group itself.
**You do not create an ALB, target group, task definition or ECS service by hand.**

> **Do this guide first.** Part A creates the AWS resources that are **shared with `sage-ui`**
> (IAM roles, cluster). The UI guide — [`UI_EXPRESS_MODE_DEPLOYMENT.md`](UI_EXPRESS_MODE_DEPLOYMENT.md) —
> only verifies they exist and adds its own repository/ECR settings. Once both are set up, the two
> services deploy independently: a push to `sage-api` never touches `sage-ui` and vice-versa.

> This guide replaces `API_GITHUB_ACTIONS_ECS_SETUP.md` (classic task-definition/service model,
> internal ALB, private subnets + NAT). That file also has a wrong account ID (`107094296439`);
> the real account is **`107094296459`**.

## Values used throughout (verified from your account, repo and screenshots)

| Value | Meaning |
|---|---|
| `107094296459` | AWS account ID |
| `us-east-1` | Region for ECR and ECS |
| `sanumolu-rnt-c` (org ID `313004951`) | GitHub organisation |
| `sanumolu-rnt-c/sage-api` (repo ID `1379718432`) | API repository — Dockerfile at repo root, branch `master` |
| `production` | GitHub Actions environment the deploy job runs in (the IAM trust policy is scoped to it) |
| `sage-prod` | ECS cluster — **shared** with `sage-ui` |
| `sage-api` | ECR repository name **and** Express Mode service name |
| `sage-github-actions-deploy-role` | IAM role GitHub Actions assumes via OIDC — already exists, **shared** with `sage-ui` |
| `sage-ecs-task-execution-role` | IAM role ECS uses to pull images and write logs — already exists, **shared** |
| `sage-ecs-infrastructure-role` | **New** IAM role Express Mode uses to create the ALB, certificate, target groups, security groups — **shared** |
| `8000` / `/api/health` | Container port / health check path |
| `https://rnt.jfrog.io/artifactory/api/pypi/pypi-org-remote/simple`, `rnt.jfrog.io` | JFrog PyPI mirror used by the build |

## What the pipeline does

```text
git push (master) in sanumolu-rnt-c/sage-api
      ↓
GitHub Actions: Deploy sage-api
      ├── pytest
      ├── assume sage-github-actions-deploy-role via OIDC   (no AWS keys stored anywhere)
      ├── docker build (JFrog build args)
      ├── push image to ECR   sage-api:<git-sha>  and  sage-api:latest
      └── create / update Express Mode service sage-api in cluster sage-prod
      ↓
https://<sage-api-endpoint>            ← printed in the workflow run summary
      ↓
consumed by sage-ui as SAGE_API_ORIGIN  (UI guide, Part B)
```

The service runs in the default VPC's public subnets behind an Application Load Balancer that
Express Mode creates and later **shares with `sage-ui`** (up to 25 services per VPC share one
ALB via host-header rules). Each service gets its own HTTPS hostname.

---

# Part A — AWS one-time setup (account `107094296459`) — shared with `sage-ui`

Do these once, in the AWS Console (or CloudShell for the CLI blocks).

## A1 — OIDC provider: already exists, nothing to do

`arn:aws:iam::107094296459:oidc-provider/token.actions.githubusercontent.com` is already in the
account (it is the `Federated` principal in `sage-github-actions-deploy-role`'s trust policy).
Optional check:

```bash
aws iam list-open-id-connect-providers
```

## A2 — Create the Express Mode infrastructure role `sage-ecs-infrastructure-role`

Your `ECS_INFRASTRUCTURE_ROLE_ARN` secret currently points at `sage-ecs-task-role`, which trusts
`ecs-tasks.amazonaws.com` and has no permissions. Express Mode needs a role trusted by
**`ecs.amazonaws.com`** with the managed policy below.

IAM Console → **Roles → Create role** → Trusted entity type: **Custom trust policy** → paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ecs.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

→ **Next** → search and tick **`AmazonECSInfrastructureRoleforExpressGatewayServices`** → **Next**
→ Role name: `sage-ecs-infrastructure-role` → **Create role**.

CLI equivalent:

```bash
aws iam create-role --role-name sage-ecs-infrastructure-role --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
```

```bash
aws iam attach-role-policy --role-name sage-ecs-infrastructure-role --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
```

Resulting ARN (used by both repositories): `arn:aws:iam::107094296459:role/sage-ecs-infrastructure-role`

## A3 — Fix the deploy role's inline policy `sage-github-actions-deploy-role-policy`

Your current policy already has the Express Mode actions, but its `PassEcsRoles` statement only
allows passing roles to `ecs-tasks.amazonaws.com`. The infrastructure role is passed to
**`ecs.amazonaws.com`**, so the first Express deploy would fail with
`iam:PassRole ... not authorized`. Replace the whole policy with this:

IAM Console → **Roles → `sage-github-actions-deploy-role` → Permissions → `sage-github-actions-deploy-role-policy` → Edit → JSON** → select all, paste, **Next → Save changes**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrPush",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
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
      "Resource": "*"
    },
    {
      "Sid": "EcsExpressMode",
      "Effect": "Allow",
      "Action": [
        "ecs:CreateCluster",
        "ecs:DescribeClusters",
        "ecs:RegisterTaskDefinition",
        "ecs:DescribeTaskDefinition",
        "ecs:CreateExpressGatewayService",
        "ecs:UpdateExpressGatewayService",
        "ecs:DescribeExpressGatewayService",
        "ecs:DescribeServices",
        "ecs:UpdateService",
        "ecs:ListServiceDeployments",
        "ecs:DescribeServiceDeployments",
        "ecs:TagResource",
        "ecs:UntagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassEcsRoles",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::107094296459:role/sage-ecs-task-execution-role",
        "arn:aws:iam::107094296459:role/sage-ecs-task-role",
        "arn:aws:iam::107094296459:role/sage-ecs-infrastructure-role"
      ],
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": [
            "ecs-tasks.amazonaws.com",
            "ecs.amazonaws.com"
          ]
        }
      }
    },
    {
      "Sid": "ServiceLinkedRoles",
      "Effect": "Allow",
      "Action": "iam:CreateServiceLinkedRole",
      "Resource": "arn:aws:iam::*:role/aws-service-role/*"
    },
    {
      "Sid": "Logs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:DescribeLogGroups",
        "logs:TagResource"
      ],
      "Resource": "*"
    }
  ]
}
```

## A4 — Trust policy: allow both repositories to assume the deploy role

The trust policy currently allows only `sage-api`. Add `sage-ui` now so the UI guide doesn't have
to touch IAM at all.

IAM Console → **Roles → `sage-github-actions-deploy-role` → Trust relationships → Edit trust policy**
→ select all, paste, **Update policy**:

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

Why three entries: the `@313004951` / `@1379718432` suffixes are GitHub's **immutable subject
claim** format (org ID / repo ID) — repositories created after 15 July 2026 use it automatically,
older ones only if opted in. The two `sage-ui` lines cover both formats. Both workflows run their
job in the `production` environment, which is why the claim ends in `:environment:production`
rather than a branch name — keep `environment: production` in the YAML.

## A5 — ECR repository `sage-api`

Most likely exists already (your current workflow pushed to it). Safe to run — an existing
repository just returns `RepositoryAlreadyExistsException`, which you can ignore.

```bash
aws ecr create-repository --repository-name sage-api --region us-east-1 --image-scanning-configuration scanOnPush=true
```

Console: **ECR → Create repository → Private → name `sage-api` → Scan on push: Enabled → Create.**

## A6 — ECS cluster `sage-prod` (shared)

Safe to run even if it already exists (returns the existing cluster):

```bash
aws ecs create-cluster --cluster-name sage-prod --region us-east-1
```

Console: **ECS → Clusters → Create cluster → name `sage-prod` → Infrastructure: AWS Fargate → Create.**

## A7 — Clean-slate check: no classic `sage-api` service may exist in `sage-prod`

If you already ran the *old* guide's Step 9 (`aws ecs create-service ...`) or the old workflow
created a service, Express Mode cannot create a service with the same name. Check:

```bash
aws ecs describe-services --cluster sage-prod --services sage-api --region us-east-1 --query "services[].{name:serviceName,status:status}" --output table
```

- Empty table / `MISSING` → nothing to do.
- `ACTIVE` service that was **not** created by Express Mode → delete it, then wait ~1 minute:

```bash
aws ecs delete-service --cluster sage-prod --service sage-api --force --region us-east-1
```

If you also created the classic `sage-api-alb`, `sage-api-tg` or `sage-api-*-sg` resources from the
old guide, delete them in **EC2 → Load Balancers / Target Groups / Security Groups** — Express Mode
will not reuse them and the ALB costs money while it exists.

## A8 — Default VPC check

Express Mode uses the default VPC's public subnets when you don't pass `subnets`. Confirm one exists:

```bash
aws ec2 describe-vpcs --filters Name=isDefault,Values=true --region us-east-1 --query "Vpcs[].VpcId" --output text
```

- Prints a `vpc-…` ID → done, leave `ECS_SUBNETS` unset.
- Prints nothing → pick two **public** subnets in two AZs of **one** VPC and set repository
  variable `ECS_SUBNETS=subnet-aaaa,subnet-bbbb` (Part B). Write the value down — the UI
  repository must use the **same** value so both services share one ALB.

---

# Part B — GitHub configuration: `sanumolu-rnt-c/sage-api`

**Settings → Secrets and variables → Actions**

**Secrets** tab — one value to fix, the other two are already correct:

| Secret | Value | Action |
|---|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::107094296459:role/sage-github-actions-deploy-role` | already set ✓ |
| `ECS_EXECUTION_ROLE_ARN` | `arn:aws:iam::107094296459:role/sage-ecs-task-execution-role` | already set ✓ |
| `ECS_INFRASTRUCTURE_ROLE_ARN` | `arn:aws:iam::107094296459:role/sage-ecs-infrastructure-role` | **update** — currently points at `sage-ecs-task-role` |

**Variables** tab:

| Variable | Value | Action |
|---|---|---|
| `AWS_REGION` | `us-east-1` | already set ✓ |
| `ECS_CLUSTER` | `sage-prod` | already set ✓ |
| `PIP_INDEX_URL` | `https://rnt.jfrog.io/artifactory/api/pypi/pypi-org-remote/simple` | already set ✓ |
| `PIP_TRUSTED_HOST` | `rnt.jfrog.io` | already set ✓ |
| `ECS_API_SERVICE` | `sage-api` | no longer read by the workflow — delete or leave |
| `ECS_API_TASK_DEFINITION` | `sage-api` | no longer read by the workflow — delete or leave |
| `ECS_SUBNETS` | *(only if A8 said so)* | optional |

**Environment:** the job declares `environment: production`. GitHub creates it automatically on
the first run; no protection rules are needed. If your organisation restricts environment creation,
create it once: **Settings → Environments → New environment → `production`**.

---

# Part C — Workflow file: `.github/workflows/deploy-api.yml`

Replace the whole file with the version below (also saved as
[`workflows/deploy-api.yml`](workflows/deploy-api.yml)).

What changed versus your current file: the three classic steps at the end (*Download current ECS
task definition* / *Render ECS task definition* / *Deploy ECS service*) are replaced by one
`aws-actions/amazon-ecs-deploy-express-service@v1` step; a secrets sanity check and a run summary
(prints the URL) are added; `concurrency` prevents two deploys racing. Your Python test steps,
`master` branch, `environment: production`, JFrog build args and image tags are unchanged.

```yaml
# sage-api: GitHub -> Amazon ECR -> Amazon ECS Express Mode
#
#   push -> master     : test, build, push to ECR (:<git-sha> and :latest), deploy to ECS Express Mode
#   workflow_dispatch  : same as push (manual run from the Actions tab)
#
# Authentication uses GitHub OIDC -> IAM role sage-github-actions-deploy-role (no AWS keys stored).
# The job runs in the GitHub environment "production" because the IAM role's trust policy is
# scoped to "...:environment:production" - do NOT remove the `environment:` line below.
#
# Required repository secrets (Settings -> Secrets and variables -> Actions -> Secrets):
#   AWS_DEPLOY_ROLE_ARN          arn:aws:iam::107094296459:role/sage-github-actions-deploy-role
#   ECS_EXECUTION_ROLE_ARN       arn:aws:iam::107094296459:role/sage-ecs-task-execution-role
#   ECS_INFRASTRUCTURE_ROLE_ARN  arn:aws:iam::107094296459:role/sage-ecs-infrastructure-role
# Repository variables (Variables tab):
#   AWS_REGION        us-east-1
#   ECS_CLUSTER       sage-prod
#   PIP_INDEX_URL     https://rnt.jfrog.io/artifactory/api/pypi/pypi-org-remote/simple
#   PIP_TRUSTED_HOST  rnt.jfrog.io
#   ECS_SUBNETS       (optional) subnet-aaaa,subnet-bbbb - only if the account has no default VPC
#
# Setup guide: SAGE_EXPRESS_MODE_DEPLOYMENT.md

name: Deploy sage-api

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
  ECR_REPOSITORY: sage-api
  ECS_CLUSTER: ${{ vars.ECS_CLUSTER || 'sage-prod' }}
  ECS_SERVICE: sage-api

concurrency:
  group: deploy-api-${{ github.ref }}
  cancel-in-progress: false

jobs:
  deploy:
    name: Test, build, push, and deploy API
    runs-on: ubuntu-latest
    environment: production

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip

      - name: Install API dependencies
        env:
          PIP_INDEX_URL: ${{ vars.PIP_INDEX_URL || 'https://pypi.org/simple' }}
          PIP_TRUSTED_HOST: ${{ vars.PIP_TRUSTED_HOST || '' }}
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements.txt
          python -m pip install -e .[dev]

      - name: Run API tests
        run: pytest

      - name: Check required repository secrets
        env:
          DEPLOY_ROLE: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          EXEC_ROLE: ${{ secrets.ECS_EXECUTION_ROLE_ARN }}
          INFRA_ROLE: ${{ secrets.ECS_INFRASTRUCTURE_ROLE_ARN }}
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
          if [ "$missing" = 1 ]; then
            echo "::error::Follow SAGE_EXPRESS_MODE_DEPLOYMENT.md Part B, then re-run this workflow."
            exit 1
          fi

      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          role-session-name: github-actions-sage-api
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
          build-args: |
            PIP_INDEX_URL=${{ vars.PIP_INDEX_URL || 'https://pypi.org/simple' }}
            PIP_TRUSTED_HOST=${{ vars.PIP_TRUSTED_HOST || '' }}
          tags: |
            ${{ steps.ecr-login.outputs.registry }}/${{ env.ECR_REPOSITORY }}:${{ github.sha }}
            ${{ steps.ecr-login.outputs.registry }}/${{ env.ECR_REPOSITORY }}:latest
          cache-from: type=gha,scope=sage-api
          cache-to: type=gha,mode=max,scope=sage-api

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
          container-port: 8000
          health-check-path: /api/health
          environment-variables: '[{"name":"PORT","value":"8000"}]'
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
            echo "### Deployed sage-api to Amazon ECS Express Mode :rocket:"
            echo ""
            echo "- **Service ARN:** ${{ steps.deploy.outputs.service-arn }}"
            echo "- **API URL:** https://$EP"
            echo "- **Health check:** https://$EP/api/health"
            echo "- **Image tag:** ${{ github.sha }}"
            echo ""
            echo "Next: set repository variable \`SAGE_API_ORIGIN\` in sanumolu-rnt-c/sage-ui to \`https://$EP\` (no trailing slash), then run Deploy sage-ui."
          } >> "$GITHUB_STEP_SUMMARY"
```

---

# Part D — Deploy

1. Push to `master`, or **Actions → Deploy sage-api → Run workflow**.
2. The first run takes **8–10 minutes** (Express Mode provisions the ALB and an ACM certificate);
   later runs take 3–4 minutes.
3. Open the run → **Summary** → copy the **API URL** exactly as printed
   (`https://<sage-api-endpoint>`).
4. **Hand it to the UI:** in `sanumolu-rnt-c/sage-ui` → Settings → Secrets and variables →
   Actions → Variables → `SAGE_API_ORIGIN` = that URL, `https://…`, **no trailing slash**.
   Then continue with [`UI_EXPRESS_MODE_DEPLOYMENT.md`](UI_EXPRESS_MODE_DEPLOYMENT.md).

From then on, every push to `master` redeploys the API only. The URL stays the same unless you
delete and recreate the `sage-api` service — if that ever happens, update `SAGE_API_ORIGIN` in the
UI repository and re-run **Deploy sage-ui**.

---

# Part E — Verification

```bash
curl -s https://<sage-api-endpoint>/api/health
```

Expect HTTP 200 with the health JSON (`"status": "ok"`, `"service": "sage-api"`).

```bash
aws ecs describe-services --cluster sage-prod --services sage-api --region us-east-1 --query "services[].{name:serviceName,status:status,running:runningCount,desired:desiredCount}" --output table
```

**Logs:** CloudWatch → Log groups → `/aws/ecs/sage-prod/sage-api-…` (Express Mode creates it), or
**ECS → Clusters → sage-prod → Services → sage-api → Logs / Health and metrics**.

**Target health (if unhealthy):** **EC2 → Target Groups** → the group tagged `AmazonECSManaged`
for `sage-api` → **Targets** tab.

---

# Troubleshooting

| Symptom (Actions log) | Cause / fix |
|---|---|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub` mismatch. The job must have `environment: production`; the `sage-api` line in A4 must be present unchanged. |
| `iam:PassRole … not authorized` on the infrastructure role | A3 not applied (`ecs.amazonaws.com` missing from `iam:PassedToService`), or the `ECS_INFRASTRUCTURE_ROLE_ARN` secret still points at `sage-ecs-task-role` (Part B). |
| `AccessDeniedException … ecs:CreateExpressGatewayService` | Inline policy from A3 not saved on `sage-github-actions-deploy-role`. |
| `Unable to assume the service linked role` | Happens on the very first ECS/ELB/auto-scaling use in an account. Re-run the workflow. |
| Service `sage-api` already exists / `InvalidParameterException` on create | A classic (non-Express) service with that name exists in `sage-prod`. A7. |
| Subnet / VPC errors, or `no default VPC` | A8: set `ECS_SUBNETS` to two public subnet IDs in one VPC. |
| Deployment never becomes healthy; tasks restart | `/api/health` must return **HTTP 200** and the app must bind `0.0.0.0:8000`. Read the CloudWatch log group first — a crash at start-up is the usual cause. |
| `CannotPullContainerError` | Image tag not in ECR (build step failed) or `sage-ecs-task-execution-role` lacks `AmazonECSTaskExecutionRolePolicy`. |
| `pip install` fails against JFrog | The mirror needs authentication. Store the credentialed URL as a **secret** `PIP_INDEX_URL` and change both `vars.PIP_INDEX_URL` references in the workflow to `secrets.PIP_INDEX_URL`. |
| `Repository secret … is not set` | Part B not finished. |

---

# Cost and cleanup

Express Mode is free; the resources it creates are billed: the Application Load Balancer
(≈ USD 16–20/month, **shared** with `sage-ui`) and one Fargate task at 0.5 vCPU / 1 GB
(≈ USD 18/month at `min-task-count: 1`). Check current pricing before leaving it running.

To remove the API: **ECS → Clusters → sage-prod → Services → sage-api → Delete**. The ALB is
deprovisioned automatically only when **no** Express service uses it any more (i.e. after
`sage-ui` is deleted too). ECR repository and IAM roles: delete only when `sage-ui` is gone as well
— see the UI guide's cleanup section for the full list.

---

# Notes

- **The API endpoint is public HTTPS.** That was the accepted POC trade-off. If `sage-api` has no
  authentication, anyone with the URL can call it — don't put sensitive data behind it. Do **not**
  lock the shared ALB's security group to an office IP: `sage-ui`'s server-side calls to the API go
  through that same ALB and would be blocked too.
- **Going to production later:** pass `subnets:` with two **private** subnet IDs and Express Mode
  will provision an **internal** ALB automatically (needs a NAT gateway or VPC endpoints so tasks
  can reach ECR/CloudWatch/JFrog). No other change to the workflow.
- **`sage-ecs-task-role`** is not passed to Express Mode because the API doesn't call AWS SDKs. If
  it ever does, add `task-role-arn: arn:aws:iam::107094296459:role/sage-ecs-task-role` to the
  deploy step (the PassRole policy in A3 already allows it).

References: [Resources created by Amazon ECS Express Mode](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html) ·
[aws-actions/amazon-ecs-deploy-express-service](https://github.com/aws-actions/amazon-ecs-deploy-express-service) ·
[AmazonECSInfrastructureRoleforExpressGatewayServices](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonECSInfrastructureRoleforExpressGatewayServices.html) ·
[GitHub immutable OIDC subject claims](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)
