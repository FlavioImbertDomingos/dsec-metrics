# jira collector

Runs JQL searches on Jira Cloud and returns one record per issue.

Each entry under `searches` is a query: the name is the query name and the value is the JQL. Records have the issue `key`, the configured `fields` flattened to plain values (a status becomes its name, a user their display name), `age_days` from `created`, and any dimensions taken from Jira fields through `dimension_fields`.

## Minimum permissions

An account with the **Browse projects** permission on the projects the searches cover, and an API token for it. Nothing else: the collector calls the search and `myself` endpoints only.

## Configuration

```yaml
id: jira-findings
plugin: jira
config:
  base_url: https://example.atlassian.net
  email: file:///run/secrets/jira_email
  api_token: file:///run/secrets/jira_token
  searches:
    open_findings: project = SEC AND labels = finding AND statusCategory != Done
  fields: [summary, status, priority, created, duedate, labels]
  dimension_fields: {business_unit: customfield_10050}
  sensitive_fields: [summary]
schedule: "0 4 * * *"
```

Issue summaries are free text. List them in `sensitive_fields` if they can hold personal data; card numbers in them are masked either way.
