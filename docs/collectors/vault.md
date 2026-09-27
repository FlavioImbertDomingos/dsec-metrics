# vault collector

Reads secrets-management evidence from a HashiCorp Vault or OpenBao server.

| Query | Records |
| --- | --- |
| `auth_methods` | Enabled auth methods: mount, type, local flag, default and maximum lease TTL. |
| `audit_devices` | Enabled audit devices: mount, type, local flag, whether accessors are HMAC-ed and whether raw logging is on. No records means Vault is not writing an audit log. |
| `transit_key_versions` | Transit keys: type, latest version, minimum decryption version, automatic rotation period, whether exportable or deletable, and the latest version's age in days. |

## Minimum permissions

A token with this policy. `sudo` on `sys/audit` is required by Vault to read the audit device list; the policy grants no write capability anywhere.

```hcl
path "sys/auth" {
  capabilities = ["read"]
}

path "sys/audit" {
  capabilities = ["read", "sudo"]
}

path "transit/keys" {
  capabilities = ["list"]
}

path "transit/keys/*" {
  capabilities = ["read"]
}
```

Replace `transit` with the mount set in `transit_mount`. Use a periodic or long-TTL token issued for this purpose, and rotate it like any other credential.

## Configuration

```yaml
id: vault-prod
plugin: vault
config:
  address: https://vault.example.com:8200
  token: file:///run/secrets/vault_token
  namespace: security            # Vault Enterprise namespaces; omit otherwise
  transit_mount: transit
  dimensions: {environment: prod}
schedule: "30 3 * * *"
```

`test-connection` calls `sys/health` and accepts standby nodes.
