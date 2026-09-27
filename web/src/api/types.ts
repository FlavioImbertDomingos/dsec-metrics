/** Response shapes of the read API (src/dsec_metrics/api/responses.py). */

export type Status = "green" | "amber" | "red" | "unknown";

export interface Point {
  measurement_id: number;
  as_of: string;
  value: number | null;
  status: Status;
  delta_previous: number | null;
  delta_baseline: number | null;
  distance_to_target: number | null;
  definition_version: number;
}

export interface Band {
  min: number | null;
  max: number | null;
  above: number | null;
  below: number | null;
}

export interface Bands {
  green: Band;
  amber: Band | null;
  red: Band | null;
}

export interface MetricSummary {
  id: string;
  name: string;
  type: string;
  question: string;
  owner: string;
  audience: string[];
  unit: string;
  frequency: string;
  higher_is_better: boolean;
  target: number | null;
  action_when_red: string;
  latest: Point | null;
}

export interface Requirement {
  ref: string;
  framework: string;
  framework_name: string;
  short_title: string | null;
}

export interface DefinitionVersion {
  version: number;
  sha256: string;
  created_at: string;
  current: boolean;
}

export interface MetricDetail extends MetricSummary {
  source: { collector: string; query: string; params: Record<string, unknown> };
  evaluation: Record<string, unknown>;
  thresholds: Record<string, unknown>;
  bands: Bands;
  baseline: { value: number; method: string; date: string } | null;
  frameworks: Requirement[];
  controls: string[];
  version: number;
  sha256: string;
  versions: DefinitionVersion[];
  definition: Record<string, unknown>;
  group_by: string[];
}

export interface Slice {
  dimensions: Record<string, string>;
  point: Point;
}

export interface MetricHistory {
  metric_id: string;
  dimensions: Record<string, string>;
  applied_filters: Record<string, string>;
  ignored_filters: string[];
  points: Point[];
  slices: Slice[];
  bands: Bands;
}

export interface BatchRef {
  sha256: string;
  collector: string;
  collector_version: string;
  instance_id: string;
  query: string;
  params: Record<string, unknown>;
  as_of: string;
  collected_at: string;
  record_count: number;
  redaction: { records?: number; pans_masked?: number; fields_dropped?: Record<string, number> };
  storage_ref: string;
}

export interface MeasurementDetail {
  metric_id: string;
  metric_name: string;
  dimensions: Record<string, string>;
  point: Point;
  definition_sha256: string;
  calculation: Record<string, unknown>;
  computed_at: string;
  batches: BatchRef[];
  missing_batches: string[];
}

export interface BatchPage {
  batch: BatchRef;
  offset: number;
  limit: number;
  total: number;
  records: Record<string, unknown>[];
}

export interface RegisterSource {
  sha256: string;
  as_of: string;
  collected_at: string;
}

export interface Dimensions {
  business_unit: string | null;
  application: string | null;
  environment: string | null;
  region: string | null;
}

export interface ExceptionItem extends Dimensions {
  exception_id: string;
  status: string;
  control_id: string | null;
  reason: string | null;
  compensating_controls: string | null;
  risk_rating: string | null;
  owner: string | null;
  root_cause: string | null;
  approved_at: string | null;
  expires_at: string | null;
  age_days: number | null;
  days_to_expiry: number | null;
}

export interface FindingItem extends Dimensions {
  finding_id: string;
  severity: string;
  status: string;
  source: string | null;
  control_id: string | null;
  owner: string | null;
  opened: string | null;
  due_date: string | null;
  repeat: boolean;
  days_open: number | null;
  days_past_due: number | null;
}

export interface Register<T> {
  source: RegisterSource | null;
  items: T[];
  skipped: number;
}

export interface ControlSummary {
  id: string;
  name: string;
  owner: string;
  status: Status;
  metric_ids: string[];
  requirement_count: number;
  open_exceptions: number;
  open_findings: number;
}

export interface ControlDetail extends ControlSummary {
  description: string;
  requirements: Requirement[];
  metrics: MetricSummary[];
  evidence: { collector: string; query: string; retain_days: number; latest: BatchRef | null }[];
  exceptions: ExceptionItem[];
  findings: FindingItem[];
}

export interface DashboardSummary {
  id: string;
  title: string;
  audience: string;
  refresh: string;
}

export interface Series {
  metric: MetricSummary;
  points: Point[];
  baseline: number | null;
  bands: Bands;
}

export interface Cell {
  row: string;
  column: string;
  value: number | null;
  status: Status;
  measurement_id: number | null;
}

export interface Bucket {
  label: string;
  count: number;
}

export type WidgetKind =
  | "stat"
  | "trend"
  | "bar"
  | "table"
  | "rag_list"
  | "heatmap"
  | "exceptions_aging"
  | "findings_burndown";

export interface Widget {
  widget: WidgetKind;
  title: string;
  width: number;
  filtered: boolean;
  note: string | null;
  metrics: MetricSummary[];
  points: Record<string, Point | null>;
  series: Series[];
  cells: Cell[];
  rows: string[];
  columns: string[];
  buckets: Bucket[];
  source: RegisterSource | null;
}

export interface Dashboard extends DashboardSummary {
  as_of: string | null;
  filters: Record<string, string>;
  dimensions: Record<string, string[]>;
  widgets: Widget[];
}

export interface ReportPackage {
  id: string;
  report_type: string;
  title: string;
  scope: Record<string, unknown>;
  period_start: string;
  period_end: string;
  frameworks: string[];
  manifest_sha256: string;
  key_fingerprint: string;
  pdf_rendered: boolean;
  generated_by: string;
  generated_at: string;
  size: number;
}

export interface AuditEvent {
  seq: number;
  occurred_at: string;
  actor: string;
  action: string;
  target: string;
  details: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface Grant {
  id: string;
  username: string;
  frameworks: string[];
  period_start: string;
  period_end: string;
  expires_at: string;
}

export interface AuditRoom {
  auditor: boolean;
  grants: Grant[];
  packages: ReportPackage[];
  access_log: AuditEvent[];
}

export interface ChainCheck {
  ok: boolean;
  checked: number;
  broken_at: number | null;
  reason: string | null;
  head: string;
}

export interface PublicKey {
  algorithm: string;
  fingerprint: string;
  pem: string;
}

export interface LinkCreated {
  url: string;
  expires_at: string;
  username: string;
}
