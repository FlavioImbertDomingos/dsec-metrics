# rest collector

Reads any JSON API described in configuration, for sources without a dedicated collector: an asset inventory, a DSPM product, an internal service.

Each entry under `queries` is a query:

| Setting | Meaning |
| --- | --- |
| `path` | Path under `base_url`, for example `/v2/assets`. No `.` or `..` segments. |
| `params` | Fixed query parameters. Booleans are sent as `true` and `false`. |
| `records_path` | Dotted path to the list of records in the response, for example `data.items`. Empty means the response is the list. |
| `pagination` | `none`, `link` (`Link: rel="next"` headers), `offset` (offset and limit parameters) or `cursor` (the response names the next cursor). |
| `page_size`, `offset_param`, `limit_param`, `total_path` | Offset paging. Paging stops on a short page or once `total_path` is reached. |
| `cursor_path`, `cursor_param` | Cursor paging: where the next cursor is in the response, and the parameter that sends it back. Paging stops when it is empty or repeats. |
| `fields` | Keep only these dotted paths from each record. Empty keeps whole records. |

Authentication is one header whose value comes from a secret reference. Other headers can be set, except ones that carry credentials (`Authorization`, `Cookie`, `X-Api-Key`, `Proxy-Authorization`); those must go through `auth`.

## Minimum permissions

Read-only access to the configured endpoints. Ask the API owner for a token scoped to read, and document the scope in the instance's `description`.

## Configuration

```yaml
id: inventory
plugin: rest
description: Asset inventory, token scope assets:read
config:
  base_url: https://inventory.example.com/api
  auth: {header: Authorization, scheme: Bearer, secret: file:///run/secrets/inventory_token}
  queries:
    assets:
      path: /v2/assets
      params: {active: true}
      records_path: data.assets
      pagination: cursor
      cursor_path: meta.next
      cursor_param: after
      fields: [id, tier, owner.team, encrypted]
  dimensions: {environment: prod}
schedule: "0 2 * * *"
```

DSPM products and similar tools that expose a JSON API can be read this way until they have their own collector.
