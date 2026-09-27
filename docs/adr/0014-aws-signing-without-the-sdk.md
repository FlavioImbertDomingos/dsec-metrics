# 0014: AWS request signing without the AWS SDK

- Status: accepted
- Date: 2026-09-27
- Deciders: maintainers

## Context

The `aws` collector needs four read queries across KMS, ACM, AWS Config and IAM. The usual way is boto3, which the brief does not name. It brings botocore and a large data package, has its own HTTP stack (urllib3) that would bypass the outbound policy in [ADR-0013](0013-outbound-http-and-ssrf.md) unless wrapped, and would be the largest dependency in the image.

The four queries use two protocols: JSON APIs (KMS, ACM, Config), which POST a JSON body with an `X-Amz-Target` header, and a Query API (IAM), read with GET. Both are signed with Signature Version 4.

## Decision

Implement SigV4 in `plugins/sdk/aws_sigv4.py` with `hmac` and `hashlib`, and send requests through the SDK's HTTP client like every other collector.

- The signer covers what the collector sends: fixed paths, simple query strings, JSON bodies, optional session tokens.
- It is tested against vectors from AWS's published SigV4 test suite and the IAM `ListUsers` example in AWS's documentation, and the collector is tested against LocalStack over the real network path.
- Only the read actions the collector declares can be sent as POST.
- Credentials are secret references. Instance roles and web identity are not supported yet (they would need a metadata or STS call); an operator provides keys or temporary credentials through a secret provider.

## Alternatives considered

- boto3. Complete and familiar, but a large new dependency with its own HTTP path, for four queries.
- A small third-party SigV4 package. Still a dependency to vet and track, for about a hundred lines of code with published test vectors.

## Consequences

- No new runtime dependency, and AWS traffic goes through the same outbound policy as everything else.
- New AWS queries must fit the JSON or Query protocol and are added by hand, with fixtures. Services that need other protocols (REST-XML such as S3) would need more signer coverage, or a decision to adopt the SDK.
- Temporary credentials from instance metadata are not fetched, which also keeps the metadata address blocked for collectors.
