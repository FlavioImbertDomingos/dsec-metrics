/** Small API responses for component tests. */
import type {
  BatchPage,
  ControlDetail,
  ControlSummary,
  Dashboard,
  DashboardSummary,
  ExceptionItem,
  FindingItem,
  MeasurementDetail,
  MetricDetail,
  MetricHistory,
  MetricSummary,
  Point,
  Register,
  Widget,
} from "@/api/types";

const SHA = "a".repeat(64);

export function point(
  id: number,
  asOf: string,
  value: number | null,
  status: Point["status"],
): Point {
  return {
    measurement_id: id,
    as_of: asOf,
    value,
    status,
    delta_previous: 1,
    delta_baseline: -2,
    distance_to_target: 3,
    definition_version: 1,
  };
}

export const KRI: MetricSummary = {
  id: "KRI-06",
  name: "Secrets older than their rotation policy",
  type: "kri",
  question: "Are stored secrets rotated on schedule?",
  owner: "secrets-platform-lead",
  audience: ["team_operations", "management"],
  unit: "count",
  frequency: "monthly",
  higher_is_better: false,
  target: 0,
  action_when_red: "Rotate overdue secrets.",
  latest: point(11, "2026-09-30", 7, "red"),
};

export const KCI: MetricSummary = {
  ...KRI,
  id: "KCI-01",
  name: "Encryption at rest coverage",
  type: "kci",
  unit: "percent",
  higher_is_better: true,
  target: 100,
  audience: ["management", "risk_committee"],
  latest: point(12, "2026-09-30", 99.5, "green"),
};

const BANDS = {
  green: { min: null, max: 3, above: null, below: null },
  amber: { min: null, max: 6, above: null, below: null },
  red: { min: null, max: null, above: 6, below: null },
};

const series = (m: MetricSummary) => ({
  metric: m,
  points: [point(1, "2026-08-31", 5, "amber"), point(11, "2026-09-30", 7, "red")],
  baseline: 4,
  bands: BANDS,
});

function widget(kind: Widget["widget"], extra: Partial<Widget> = {}): Widget {
  return {
    widget: kind,
    title: `A ${kind} widget`,
    width: 6,
    filtered: false,
    note: null,
    metrics: [KRI],
    points: { "KRI-06": KRI.latest },
    series: [],
    cells: [],
    rows: [],
    columns: [],
    buckets: [],
    source: null,
    ...extra,
  };
}

export const DASHBOARD: Dashboard = {
  id: "risk-committee",
  title: "Risk committee",
  audience: "risk_committee",
  refresh: "monthly",
  as_of: "2026-09-30",
  filters: {},
  dimensions: { business_unit: ["cards", "payments"] },
  widgets: [
    widget("stat", { width: 3, series: [series(KRI)] }),
    widget("rag_list", {
      width: 12,
      metrics: [KRI, KCI],
      points: { "KRI-06": KRI.latest, "KCI-01": KCI.latest },
    }),
    widget("table", { metrics: [KCI], points: { "KCI-01": KCI.latest } }),
    widget("trend", {
      series: [series(KRI), series(KCI)],
      note: "KCI-01 not broken down by region; showing overall values.",
    }),
    widget("bar", {
      rows: ["cards", "payments"],
      cells: [
        { row: "cards", column: "KRI-06", value: 4, status: "amber", measurement_id: 21 },
        { row: "payments", column: "KRI-06", value: 3, status: "green", measurement_id: 22 },
      ],
    }),
    widget("heatmap", {
      rows: ["cards"],
      columns: ["KRI-06", "DS-SM-02"],
      cells: [
        { row: "cards", column: "KRI-06", value: 4, status: "amber", measurement_id: 21 },
        { row: "cards", column: "DS-SM-02", value: null, status: "red", measurement_id: null },
      ],
    }),
    widget("exceptions_aging", {
      buckets: [
        { label: "0 to 90 days", count: 3 },
        { label: "over 365 days", count: 1 },
      ],
    }),
    widget("findings_burndown", {
      series: [series(KRI)],
      buckets: [
        { label: "critical", count: 1 },
        { label: "high", count: 2 },
      ],
    }),
  ],
};

export const DASHBOARDS: DashboardSummary[] = [
  {
    id: "team-operations",
    title: "Team operations",
    audience: "team_operations",
    refresh: "daily",
  },
  { id: "risk-committee", title: "Risk committee", audience: "risk_committee", refresh: "monthly" },
];

export const METRIC: MetricDetail = {
  ...KRI,
  source: { collector: "sample", query: "secrets_inventory", params: {} },
  evaluation: { kind: "count" },
  thresholds: {},
  bands: BANDS,
  baseline: { value: 4, method: "manual count", date: "2025-10-31" },
  frameworks: [
    {
      ref: "pci-dss-4.0.1:8.6.3",
      framework: "pci-dss-4.0.1",
      framework_name: "PCI DSS",
      short_title: "System account passwords",
    },
  ],
  controls: ["DS-SM-02"],
  version: 2,
  sha256: SHA,
  versions: [
    { version: 2, sha256: SHA, created_at: "2026-09-27T00:00:00Z", current: true },
    { version: 1, sha256: "b".repeat(64), created_at: "2026-09-01T00:00:00Z", current: false },
  ],
  definition: { id: "KRI-06" },
  group_by: ["business_unit"],
};

export const HISTORY: MetricHistory = {
  metric_id: "KRI-06",
  dimensions: {},
  applied_filters: {},
  ignored_filters: [],
  points: [point(1, "2026-08-31", 5, "amber"), point(11, "2026-09-30", 7, "red")],
  slices: [{ dimensions: { business_unit: "cards" }, point: point(21, "2026-09-30", 4, "amber") }],
  bands: BANDS,
};

export const BATCH_REF = {
  sha256: SHA,
  collector: "sample",
  collector_version: "1.0.0",
  instance_id: "sample",
  query: "secrets_inventory",
  params: {},
  as_of: "2026-09-30",
  collected_at: "2026-09-30T02:05:00Z",
  record_count: 120,
  redaction: { records: 120, pans_masked: 2, fields_dropped: { card_holder_name: 1 } },
  storage_ref: "db:inline",
};

export const MEASUREMENT: MeasurementDetail = {
  metric_id: "KRI-06",
  metric_name: KRI.name,
  dimensions: {},
  point: point(11, "2026-09-30", 7, "red"),
  definition_sha256: SHA,
  calculation: { kind: "count", filtered_records: 7 },
  computed_at: "2026-09-30T03:00:00Z",
  batches: [BATCH_REF],
  missing_batches: ["c".repeat(64)],
};

export const BATCH: BatchPage = {
  batch: BATCH_REF,
  offset: 0,
  limit: 50,
  total: 120,
  records: [
    { secret_path: "kv/cards/app/secret-000", overdue: true, nested: { a: 1 }, empty: null },
    { secret_path: "kv/cards/app/secret-001", overdue: false },
  ],
};

export const EXCEPTION: ExceptionItem = {
  exception_id: "EX-0001",
  status: "approved",
  control_id: "DS-SM-02",
  reason: "Legacy system",
  compensating_controls: "Monitoring",
  risk_rating: "high",
  owner: "owner-01",
  root_cause: "legacy_platform",
  approved_at: "2026-01-01",
  expires_at: "2026-10-15",
  age_days: 272,
  days_to_expiry: 15,
  business_unit: "cards",
  application: "vault",
  environment: "prod",
  region: "amer",
};

export const EXCEPTIONS: Register<ExceptionItem> = {
  source: { sha256: SHA, as_of: "2026-09-30", collected_at: "2026-09-30T02:05:00Z" },
  items: [
    EXCEPTION,
    {
      ...EXCEPTION,
      exception_id: "EX-0002",
      days_to_expiry: -5,
      expires_at: "2026-09-25",
      business_unit: "payments",
      root_cause: "design_gap",
    },
  ],
  skipped: 1,
};

export const FINDING: FindingItem = {
  finding_id: "F-1",
  severity: "high",
  status: "open",
  source: "internal_audit",
  control_id: "DS-SM-02",
  owner: null,
  opened: "2026-08-01",
  due_date: "2026-09-01",
  repeat: true,
  days_open: 60,
  days_past_due: 29,
  business_unit: "cards",
  application: null,
  environment: null,
  region: null,
};

export const FINDINGS: Register<FindingItem> = {
  source: EXCEPTIONS.source,
  items: [FINDING, { ...FINDING, finding_id: "F-2", severity: "low", business_unit: "retail" }],
  skipped: 0,
};

const SECRETS_CONTROL: ControlSummary = {
  id: "DS-SM-02",
  name: "Secrets are rotated",
  owner: "secrets-platform-lead",
  status: "red",
  metric_ids: ["KRI-06"],
  requirement_count: 2,
  open_exceptions: 2,
  open_findings: 1,
};

export const CONTROLS: ControlSummary[] = [
  SECRETS_CONTROL,
  {
    id: "DS-EN-01",
    name: "Data at rest is encrypted",
    owner: "data-protection-lead",
    status: "green",
    metric_ids: ["KCI-01"],
    requirement_count: 1,
    open_exceptions: 0,
    open_findings: 0,
  },
];

export const CONTROL: ControlDetail = {
  ...SECRETS_CONTROL,
  description: "Secrets are rotated within policy.",
  requirements: METRIC.frameworks,
  metrics: [KRI],
  evidence: [
    { collector: "sample", query: "secrets_inventory", retain_days: 400, latest: BATCH_REF },
    { collector: "sample", query: "other", retain_days: 30, latest: null },
  ],
  exceptions: [EXCEPTION],
  findings: [FINDING],
};
