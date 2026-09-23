# CID 460 — Enable Content Encoding for REST API Gateway

Reference notes for remediating Qualys control **CID-460 (Medium)**: *Ensure content
encoding is enabled for REST API Gateway* — tracked in
[RNTINFSRUM-12954](https://rntinscru.atlassian.net/browse/RNTINFSRUM-12954).

## Task

Enable payload compression (content encoding) on the REST API Gateway(s) flagged as
failing by Qualys, using the remediation steps shared by Richard Castellano.

> Before starting, confirm the actual list of failing REST API IDs for **your**
> account (`4407-4423-6814` / RNTAPIData.Dev) from the attachment on the Jira ticket —
> the account IDs shown in the Qualys evidence screenshot (`004383462392`,
> `753593142157`, etc.) don't match this account, so don't assume `PrivateEDASAPI`
> (`v5gj80kkol`) is the failing resource without checking.

## Why the Invoke URL gave a DNS error

`PrivateEDASAPI` is a **Private** API Gateway (endpoint type `PRIVATE`). Private APIs
have no public DNS entry — the `execute-api.us-east-1.amazonaws.com` hostname only
resolves from inside the VPC via an interface VPC endpoint. Pasting the Invoke URL
into a normal browser will always fail with `DNS_PROBE_STARTED`, regardless of the
content encoding setting. That error is unrelated to this remediation and is not a
valid way to test a private API from outside the VPC.

## Remediation steps (AWS Console)

1. Sign in to the [API Gateway console](https://console.aws.amazon.com/apigateway).
2. Choose the REST API to remediate (e.g. `PrivateEDASAPI`).
3. In the left nav, under that API, click **API settings** (not **Stages** — this is
   the step that's easy to miss).
4. Scroll to the **Content Encoding** section.
5. Check **Content Encoding enabled**.
6. Enter a **Minimum compression size** in bytes (0–10,485,760). `0` compresses every
   payload; a small threshold (e.g. `150` or `1024`) skips compressing tiny responses.
7. Click **Save Changes**.

## Remediation steps (AWS CLI / CloudShell)

No local CLI setup needed — use **CloudShell** from the console (top nav `>_` icon,
inherits your console session credentials):

```bash
aws apigateway update-rest-api \
  --rest-api-id v5gj80kkol \
  --region us-east-1 \
  --patch-operations op=replace,path=/minimumCompressionSize,value=0
```

## How to verify

Don't use the public Invoke URL. Use one of these instead:

- **Console reload (fastest)**: navigate away from **API settings** (e.g. to
  **Stages**) and back. If the checkbox is still checked and the minimum size value
  persisted, the setting is saved.
- **CloudShell / CLI**:
  ```bash
  aws apigateway get-rest-api --rest-api-id v5gj80kkol --region us-east-1 --query minimumCompressionSize
  ```
- **Export API definition**: on the **Resources** page, **Actions → Export** the
  Swagger/OpenAPI JSON. Look for
  `"x-amazon-apigateway-minimum-compression-size"` at the top level.
- **Runtime check** (real compressed response): call the invoke URL with
  `Accept-Encoding: gzip` from *inside* the VPC (EC2/Cloud9 in the VPC, or via
  VPN/Direct Connect) — not from a local browser, since the API is private.
- **Authoritative confirmation**: the next Qualys rescan should show this resource ID
  move from FAIL to PASS on control 460.

## Repeat per resource

Apply the same steps to every REST API ID on the account's failing-resources list
(from the Jira attachment), not just `v5gj80kkol`.
