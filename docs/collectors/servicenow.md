# servicenow collector

Reads rows from ServiceNow tables through the Table API, for example GRC issues or policy exceptions.

Each entry under `tables` is a query: the table, an encoded query (`sysparm_query`), the fields to keep, and dimensions taken from fields. Values are display values, so choice fields arrive as their labels.

## Minimum permissions

- A dedicated integration user with web service access and no interactive login.
- Read access to each configured table through ACLs, for example the `snc_read_only` role plus read ACLs on those tables. No write, create or delete ACLs.

## Configuration

```yaml
id: servicenow-grc
plugin: servicenow
config:
  instance_url: https://example.service-now.com
  username: file:///run/secrets/sn_user
  password: file:///run/secrets/sn_password
  page_size: 500
  tables:
    open_issues:
      table: sn_grc_issue
      query: active=true^ORDERBYnumber
      fields: [number, state, priority, opened_at, due_date, assigned_to]
      dimension_fields: {business_unit: u_business_unit}
schedule: "0 4 * * *"
```

Order the query by a stable field (`ORDERBYnumber`) so offset paging does not skip or repeat rows while the table changes.
