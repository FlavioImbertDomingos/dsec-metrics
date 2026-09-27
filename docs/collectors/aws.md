# aws collector

Reads key management, certificate, configuration and IAM evidence from one AWS account and region.

| Query | Records |
| --- | --- |
| `kms_key_rotation` | Customer-managed KMS keys: state, key spec, origin, whether rotation is supported and enabled, rotation period, creation date and age in days. AWS-managed keys are skipped. |
| `acm_certificates` | ACM certificates: domain, status, type, whether in use, expiry date and days to expiry (negative once expired). |
| `config_rule_compliance` | AWS Config rules: compliance type and the number of non-compliant resources. |
| `iam_access_key_age` | IAM users' access keys: user, key ID, status, creation date and age in days. The key ID is an identifier; the secret part of a key is never returned by these APIs. |

Every record also has `account` (the `account_label` setting), `region` and the configured `dimensions`.

## Minimum permissions

Attach this policy to a dedicated IAM user or role. It grants read and list actions only.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DsecMetricsReadOnly",
      "Effect": "Allow",
      "Action": [
        "kms:ListKeys",
        "kms:DescribeKey",
        "kms:GetKeyRotationStatus",
        "acm:ListCertificates",
        "acm:DescribeCertificate",
        "config:DescribeComplianceByConfigRule",
        "iam:ListUsers",
        "iam:ListAccessKeys"
      ],
      "Resource": "*"
    }
  ]
}
```

KMS key policies must also let the principal call `kms:DescribeKey` and `kms:GetKeyRotationStatus`. If one key's policy does not, the run fails with the HTTP error, so a gap in access is visible instead of a key silently missing from the count.

## Configuration

```yaml
id: aws-prod-eu
plugin: aws
config:
  region: eu-west-1
  access_key_id: file:///run/secrets/aws_key_id
  secret_access_key: file:///run/secrets/aws_secret_key
  # session_token: file:///run/secrets/aws_session_token   # for temporary credentials
  account_label: prod-payments
  dimensions: {environment: prod, business_unit: payments}
schedule: "15 3 * * *"
```

Allow the endpoints in `DSEC_COLLECTOR_ALLOWED_HOSTS`: `kms.<region>.amazonaws.com`, `acm.<region>.amazonaws.com`, `config.<region>.amazonaws.com` and `iam.amazonaws.com`. For VPC endpoints or a test endpoint, set `endpoint_url`; it replaces every service endpoint.

Requests are signed with Signature Version 4 by the SDK, without the AWS SDK for Python ([ADR-0014](../adr/0014-aws-signing-without-the-sdk.md)).

## Tests

Contract tests replay recorded responses (`tests/contract/fixtures/aws/`). An integration test runs the collector against LocalStack over the real network path, with SigV4 and the outbound policy; LocalStack does not implement `DescribeComplianceByConfigRule`, so that query is covered by its contract test only.
