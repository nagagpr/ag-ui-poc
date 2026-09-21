# GitHub Actions → Amazon ECR → Amazon ECS Express Mode

One-time setup guide for the automated container deployment pipeline defined in
[`.github/workflows/deploy-ecs.yml`](../.github/workflows/deploy-ecs.yml).

> **Why not AWS App Runner?** AWS App Runner stopped accepting new customers on
> **April 30, 2026**. Accounts without an existing App Runner service cannot create one.
> AWS's recommended replacement is **Amazon ECS Express Mode**, which does the same job:
> give it a container image and it provisions a Fargate service, an Application Load
> Balancer with HTTPS, auto scaling and logging for you.

## What the pipeline does

```text
git push (main)
      ↓
GitHub Actions
      ├── assume IAM role via OIDC          (no AWS access keys stored anywhere)
      ├── docker build
      ├── push image to Amazon ECR          aws-react-poc:<git-sha>  and  :latest
      └── create / update ECS Express Mode service
      ↓
HTTPS Application URL (printed in the workflow run summary)
```

After the setup below, every push to `main` deploys automatically. You can also start a
deployment by hand: **Actions → Deploy to Amazon ECS (Express Mode) → Run workflow**.

## Values used throughout

| Placeholder / value | Meaning |
|---|---|
| `<AWS_ACCOUNT_ID>` | Your 12-digit AWS account ID (top-right of the AWS Console) |
| `us-east-1` | Region for ECR and ECS (change in the workflow `env:` block if needed) |
| `nagagpr/aws-react-poc` | GitHub organisation/user and repository name |
| `aws-react-poc` | Amazon ECR repository name **and** ECS service name |

## Prerequisites

- An AWS account where you can create IAM roles and identity providers (admin access).
- The GitHub repository `nagagpr/aws-react-poc` with this project pushed to `main`.
- An **Amazon ECR private repository** named `aws-react-poc` in `us-east-1`
  (ECR Console → Repositories → Create repository → Private → name `aws-react-poc`).
- A **default VPC** in `us-east-1` with at least two public subnets in two Availability
  Zones (every account has one unless it was deleted).

---

## Step 1 — Add GitHub as an OpenID Connect identity provider

IAM Console → **Identity providers** → **Add provider**:

| Field | Value |
|---|---|
| Provider type | **OpenID Connect** |
| Provider URL | `https://token.actions.githubusercontent.com` |
| Audience | `sts.amazonaws.com` |

Click **Add provider**. If the provider already exists, skip this step.

---

## Step 2 — Role 1: `github-actions-aws-react-poc` (assumed by GitHub Actions)

IAM Console → **Roles** → **Create role**:

1. Trusted entity type: **Web identity**
2. Identity provider: `token.actions.githubusercontent.com` — Audience: `sts.amazonaws.com`
3. GitHub organization: `nagagpr` — GitHub repository: `aws-react-poc` — GitHub branch: `main`
4. **Next** → Add permissions: leave everything unticked → **Next**
5. Role name: `github-actions-aws-react-poc` → **Create role**
6. Open the role → **Permissions** tab → **Add permissions ▾ → Create inline policy** →
   **JSON** tab → paste the policy below (replace `<AWS_ACCOUNT_ID>` twice) →
   **Next** → Policy name: `deploy-aws-react-poc` → **Create policy**

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
        "arn:aws:iam::<AWS_ACCOUNT_ID>:role/ecsTaskExecutionRole",
        "arn:aws:iam::<AWS_ACCOUNT_ID>:role/ecsInfrastructureRoleForExpressServices"
      ]
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
      "Action": ["logs:CreateLogGroup", "logs:DescribeLogGroups", "logs:TagResource"],
      "Resource": "*"
    }
  ]
}
```

The wizard writes the **trust policy** for you. Check the role's **Trust relationships**
tab — it should look like this (only runs from the `main` branch of this repository can
assume the role):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<AWS_ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:nagagpr/aws-react-poc:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

If your console version does not offer the organisation/repository/branch fields, choose
**Custom trust policy** instead and paste the JSON above.

---

## Step 3 — Role 2: `ecsTaskExecutionRole` (lets ECS pull the image and write logs)

First search IAM → **Roles** for `ecsTaskExecutionRole`. **It often already exists** —
ECS creates it automatically. If it exists, confirm it has
`AmazonECSTaskExecutionRolePolicy` attached and go to Step 4.

If it does not exist: **Create role** → Trusted entity type: **Custom trust policy** → paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

→ **Next** → search and tick **`AmazonECSTaskExecutionRolePolicy`** → **Next** →
Role name: `ecsTaskExecutionRole` → **Create role**.

---

## Step 4 — Role 3: `ecsInfrastructureRoleForExpressServices` (lets ECS create the ALB, certificate, target groups)

**Create role** → Trusted entity type: **Custom trust policy** → paste:

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

→ **Next** → search and tick **`AmazonECSInfrastructureRoleforExpressGatewayServices`** →
**Next** → Role name: `ecsInfrastructureRoleForExpressServices` → **Create role**.

---

## Step 5 — Add the three repository secrets in GitHub

GitHub → `nagagpr/aws-react-poc` → **Settings → Secrets and variables → Actions →
New repository secret**. Create these three (replace `<AWS_ACCOUNT_ID>`):

| Secret name | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/github-actions-aws-react-poc` |
| `ECS_EXECUTION_ROLE_ARN` | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/ecsTaskExecutionRole` |
| `ECS_INFRASTRUCTURE_ROLE_ARN` | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/ecsInfrastructureRoleForExpressServices` |

These are role ARNs, not credentials. They are stored as secrets only so the account ID
stays out of the repository and the workflow logs.

---

## Step 6 — Run the pipeline

Either push any commit to `main`, or open **Actions → Deploy to Amazon ECS (Express Mode)
→ Run workflow**.

- The first run takes about **8–10 minutes** (it provisions the load balancer and an ACM
  certificate). Later runs take 3–4 minutes.
- When the run finishes, open its **Summary** — the HTTPS **URL** of the service is listed
  there. The same URL is shown in the ECS Console: **Clusters → default → Services →
  aws-react-poc**.
- The page served at that URL is the same React dashboard as `npm run dev` and the local
  Docker container.

## Verify from the AWS CLI (optional)

```bash
aws iam get-role --role-name github-actions-aws-react-poc --query Role.Arn
```

```bash
aws iam list-attached-role-policies --role-name ecsTaskExecutionRole
```

```bash
aws iam list-attached-role-policies --role-name ecsInfrastructureRoleForExpressServices
```

```bash
aws ecr describe-images --repository-name aws-react-poc --region us-east-1
```

```bash
aws ecs describe-services --cluster default --services aws-react-poc --region us-east-1 --query "services[0].{status:status,running:runningCount,desired:desiredCount}"
```

---

## Troubleshooting

| Symptom (in the Actions log) | Cause / fix |
|---|---|
| `Repository secret AWS_DEPLOY_ROLE_ARN is not set` | Step 5 not done yet. Add the secrets, then re-run the workflow. |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy mismatch. Check Role 1 → Trust relationships: `sub` must be `repo:nagagpr/aws-react-poc:ref:refs/heads/main` and `aud` must be `sts.amazonaws.com`. The OIDC provider from Step 1 must exist. |
| `RepositoryNotFoundException` on push | The ECR repository `aws-react-poc` does not exist in `us-east-1`. Create it (see Prerequisites). |
| `iam:PassRole ... is not authorized` | The `PassEcsRoles` statement in Role 1's inline policy has the wrong account ID or role names. |
| `Unable to assume the service linked role` | Happens on the very first ECS service in an account. Re-run the workflow. |
| Service created but deployment never becomes healthy | Health check must return HTTP 200. The workflow sets `health-check-path: /` and `container-port: 80` to match the Nginx image — keep them if you edit the workflow. |
| `AccessDeniedException ... with an explicit deny ... AWSCompromisedKeyQuarantine` | An access key of that IAM user was exposed and AWS quarantined the user. Rotate the key, review CloudTrail, then remove the quarantine policy. This pipeline avoids the problem entirely by using OIDC instead of keys. |

---

## Cost and cleanup

Express Mode itself is free, but the resources it creates are billed continuously:
the Application Load Balancer (roughly USD 16–20 per month) and the Fargate task
(0.25 vCPU / 0.5 GB as configured in the workflow). Verify current AWS pricing before
leaving the service running.

To remove everything after the demo:

1. ECS Console → **Clusters → default → Services → aws-react-poc → Delete**
   (Express Mode deprovisions the load balancer when no service uses it any more).
2. ECR Console → **Repositories → aws-react-poc → Delete** (optional, removes the images).
3. IAM Console → **Roles** → delete `github-actions-aws-react-poc`,
   `ecsInfrastructureRoleForExpressServices` (and `ecsTaskExecutionRole` only if nothing
   else uses it).
4. IAM Console → **Identity providers** → delete `token.actions.githubusercontent.com`
   (only if no other repository uses it).
5. GitHub → **Settings → Secrets and variables → Actions** → delete the three secrets.
