# IP-Based Resource Policy for API Gateway (REST API)

Reference notes for restricting a REST API Gateway to a specific set of source IPs
using a **resource policy** (allow all invokes, then deny everything except an
allow-list of IPs).

## Example policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowInvokeFromAnywhere",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "execute-api:Invoke",
      "Resource": "arn:aws:execute-api:us-east-1:440744236814:v5gj80kkol/*"
    },
    {
      "Sid": "DenyIfNotAllowedIp",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "execute-api:Invoke",
      "Resource": "arn:aws:execute-api:us-east-1:440744236814:v5gj80kkol/*",
      "Condition": {
        "NotIpAddress": {
          "aws:SourceIp": [
            "96.241.114.211/32",
            "203.0.113.0/24"
          ]
        }
      }
    }
  ]
}
```

**How it works**: statement 1 allows invocation from anyone; statement 2 then denies
invocation from anyone whose source IP is *not* in the list. Because an explicit
`Deny` always wins over an `Allow` in IAM evaluation, the net effect is "allow only
these IPs/CIDR ranges." Add `/32` for a single IP, or a CIDR block for a range.

> Values above are for **account `440744236814`** (`4407-4423-6814` /
> RNTAPIData.Dev), region `us-east-1`, REST API ID `v5gj80kkol` (`PrivateEDASAPI`).
> Replace the IP list with the actual allow-listed source IPs/CIDRs for this API.
> `Resource: ".../*"` covers all stages/methods — scope it down to a specific stage
> (e.g. `.../dev/GET/*`) if you only want to restrict one stage.
>
> ⚠️ **`v5gj80kkol` / PrivateEDASAPI is a Private API Gateway.** `aws:SourceIp`
> conditions do **not** reliably restrict private APIs (see Common Pitfalls below) —
> for this specific API you likely want `aws:SourceVpce` / `aws:SourceVpc`
> conditions instead of, or in addition to, the IP-based ones shown here.

## Steps to apply (AWS Console)

1. Sign in to the [API Gateway console](https://console.aws.amazon.com/apigateway)
   in the **RNTAPIData.Dev** account (`440744236814`), region **us-east-1**.
2. Choose the REST API `PrivateEDASAPI` (ID `v5gj80kkol`).
3. In the left nav, click **Resource policy**.
4. Paste the policy JSON (with your account ID, API ID, and IP allow-list filled in)
   into the editor.
5. Click **Save**.
6. **Deploy the API** to the target stage — resource policy changes do **not** take
   effect until you redeploy:
   - Go to **Resources** → **Actions** (or the **Deploy API** button) → select the
     stage (e.g. `dev`) → **Deploy**.

## Steps to apply (CLI / CloudShell)

No local CLI setup needed — use CloudShell from the console top nav (`>_` icon):

```bash
aws apigateway update-rest-api \
  --rest-api-id v5gj80kkol \
  --region us-east-1 \
  --patch-operations op=replace,path=/policy,value='<url-encoded-or-escaped-policy-json>'
```

Then deploy the stage so the policy takes effect:

```bash
aws apigateway create-deployment \
  --rest-api-id v5gj80kkol \
  --region us-east-1 \
  --stage-name dev
```

## How to verify

- **Console reload**: reopen **Resource policy** and confirm the saved JSON matches
  what you entered.
- **From an allowed IP**: call the Invoke URL — should succeed (`200`, or whatever
  the backend returns).
- **From a non-allowed IP**: call the Invoke URL — should get `403 Forbidden` with a
  message like `"User: anonymous is not authorized to perform: execute-api:Invoke..."`.
- **CloudShell / CLI**:
  ```bash
  aws apigateway get-rest-api --rest-api-id v5gj80kkol --region us-east-1 --query policy
  ```

## Common pitfalls

- **Forgetting to redeploy** the stage after saving the resource policy — the console
  edit alone does not propagate to the live endpoint.
- **Private APIs**: if the REST API's endpoint type is `PRIVATE`, IP-based conditions
  on `aws:SourceIp` won't work as expected for traffic arriving through a VPC
  endpoint (the source IP AWS sees is the ENI's, not the original client's). Use
  `aws:SourceVpce` / `aws:SourceVpc` conditions instead for private APIs.
- **IPv6 clients**: if any allowed client may connect over IPv6, add the equivalent
  IPv6 addresses/ranges to the `NotIpAddress` list, or they'll be blocked.
- **Wrong ARN scope**: `.../*` applies to every stage and method; narrow the
  `Resource` ARN if the restriction should only apply to specific stages/routes.
