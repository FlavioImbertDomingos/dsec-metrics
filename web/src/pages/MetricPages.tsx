import { useBatch, useMeasurement, useMetric, useMetricHistory, useMetrics } from "@/api/hooks";
import type { Band, Bands, MetricSummary } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { Facts, JsonBlock, Section } from "@/components/Details";
import { FilterBar } from "@/components/FilterBar";
import { ErrorState, Loading, PageHeader } from "@/components/States";
import { StatusBadge } from "@/components/Status";
import { Button } from "@/components/ui/button";
import { DIMENSIONS, useFilters } from "@/lib/filters";
import { formatDate, formatValue, humanize, shortHash } from "@/lib/format";
import { Link } from "@/lib/router";
import { TrendWidget } from "@/widgets/ChartWidgets";
import { Delta, MetricLink, ValueLink } from "@/widgets/common";

export function MetricsPage() {
  const metrics = useMetrics();
  if (metrics.isError) return <ErrorState error={metrics.error} />;
  if (!metrics.data) return <Loading what="metrics" />;
  const rank = { red: 0, amber: 1, unknown: 2, green: 3 };
  return (
    <>
      <PageHeader title="Metrics" lead="Every agreed indicator, with its latest value." />
      <div className="rounded-card border-[0.5px] border-border bg-surface p-4">
        <DataTable<MetricSummary>
          caption="Metric catalog"
          data={metrics.data}
          rowKey={(m) => m.id}
          columns={[
            {
              id: "metric",
              header: "Metric",
              accessorFn: (m) => m.id,
              cell: ({ row }) => <MetricLink metric={row.original} />,
            },
            { id: "type", header: "Type", accessorFn: (m) => m.type.toUpperCase() },
            {
              id: "status",
              header: "Status",
              accessorFn: (m) => rank[m.latest?.status ?? "unknown"],
              cell: ({ row }) => <StatusBadge status={row.original.latest?.status ?? "unknown"} />,
            },
            {
              id: "value",
              header: "Value",
              accessorFn: (m) => m.latest?.value ?? -Infinity,
              cell: ({ row }) => <ValueLink point={row.original.latest} metric={row.original} />,
            },
            { id: "owner", header: "Owner", accessorFn: (m) => m.owner },
            { id: "frequency", header: "Frequency", accessorFn: (m) => m.frequency },
          ]}
        />
      </div>
    </>
  );
}

function bandText(band: Band | null, unit: string): string {
  if (!band) return "Not set";
  const parts = [];
  if (band.min !== null) parts.push(`at least ${formatValue(band.min, unit)}`);
  if (band.above !== null) parts.push(`above ${formatValue(band.above, unit)}`);
  if (band.max !== null) parts.push(`at most ${formatValue(band.max, unit)}`);
  if (band.below !== null) parts.push(`below ${formatValue(band.below, unit)}`);
  return parts.length ? parts.join(" and ") : "Any value";
}

function BandList({ bands, unit }: { bands: Bands; unit: string }) {
  return (
    <ul className="space-y-1.5 text-sm">
      {(["green", "amber", "red"] as const).map((s) => (
        <li key={s} className="flex items-center gap-2">
          <StatusBadge status={s} className="w-20" />
          {bandText(bands[s], unit)}
        </li>
      ))}
      <li className="flex items-center gap-2">
        <StatusBadge status="unknown" className="w-20" />
        No data, or the last collection is older than twice the frequency
      </li>
    </ul>
  );
}

export function MetricDetailPage({ id }: { id: string }) {
  const [filters, setFilters] = useFilters();
  const metric = useMetric(id);
  const history = useMetricHistory(id, filters);
  if (metric.isError) return <ErrorState error={metric.error} />;
  if (history.isError) return <ErrorState error={history.error} />;
  if (!metric.data || !history.data) return <Loading what="the metric" />;
  const m = metric.data;
  const h = history.data;
  const current = h.points.at(-1) ?? null;
  const options: Record<string, string[]> = {};
  for (const s of h.slices) {
    for (const [k, v] of Object.entries(s.dimensions)) {
      options[k] = [...new Set([...(options[k] ?? []), v])].sort();
    }
  }
  const sliceName = Object.values(h.dimensions).join(", ") || "all business units";

  return (
    <>
      <PageHeader
        title={
          <>
            <span>{m.id}</span> {m.name}
          </>
        }
        lead={m.question}
      />
      <FilterBar options={options} filters={filters} onChange={setFilters} />
      {h.ignored_filters.length > 0 && (
        <p className="mb-4 text-sm text-muted-foreground">
          This metric is not broken down by{" "}
          {h.ignored_filters.map((f) => humanize(f).toLowerCase()).join(", ")}; showing the overall
          value.
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Current value">
          <div className="flex items-baseline gap-3">
            <ValueLink point={current} metric={m} className="text-4xl font-semibold" />
            <StatusBadge status={current?.status ?? "unknown"} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {sliceName}, {current ? formatDate(current.as_of) : "no data"}
          </p>
          <div className="mt-3 flex flex-col gap-1">
            <Delta value={current?.delta_previous} metric={m} label="vs last period" />
            <Delta value={current?.delta_baseline} metric={m} label="vs baseline" />
            <Delta value={current?.distance_to_target} metric={m} label="vs target" />
          </div>
        </Section>
        <Section title="Thresholds">
          <BandList bands={h.bands} unit={m.unit} />
          {m.target !== null && (
            <p className="mt-3 text-sm">Target {formatValue(m.target, m.unit)}</p>
          )}
        </Section>
        <Section title="Ownership">
          <Facts
            items={[
              ["Owner", humanize(m.owner)],
              ["Type", m.type.toUpperCase()],
              ["Frequency", humanize(m.frequency)],
              ["When red", m.action_when_red],
              [
                "Baseline",
                m.baseline
                  ? `${formatValue(m.baseline.value, m.unit)} (${m.baseline.method}, ${formatDate(m.baseline.date)})`
                  : "Not set",
              ],
            ]}
          />
        </Section>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Section title="History">
          <TrendWidget
            widget={{
              widget: "trend",
              title: `${m.id} history`,
              width: 12,
              filtered: true,
              note: null,
              metrics: [m],
              points: {},
              series: [
                {
                  metric: m,
                  points: h.points,
                  baseline:
                    m.baseline && !Object.keys(h.dimensions).length ? m.baseline.value : null,
                  bands: h.bands,
                },
              ],
              cells: [],
              rows: [],
              columns: [],
              buckets: [],
              source: null,
            }}
          />
        </Section>
        <Section title="Breakdown">
          {h.slices.length === 0 ? (
            <p className="text-sm text-muted-foreground">This metric is not broken down.</p>
          ) : (
            <table className="w-full text-sm">
              <caption className="sr-only">Latest value by slice</caption>
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th scope="col" className="px-2 py-1 font-medium">
                    Slice
                  </th>
                  <th scope="col" className="px-2 py-1 font-medium">
                    Value
                  </th>
                  <th scope="col" className="px-2 py-1 font-medium">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {h.slices.map((s) => {
                  const label = DIMENSIONS.filter((d) => s.dimensions[d])
                    .map((d) => s.dimensions[d])
                    .join(", ");
                  return (
                    <tr key={label} className="border-t-[0.5px] border-border">
                      <th scope="row" className="px-2 py-1 text-left font-normal">
                        {label}
                      </th>
                      <td className="px-2 py-1">
                        <ValueLink point={s.point} metric={m} />
                      </td>
                      <td className="px-2 py-1">
                        <StatusBadge status={s.point.status} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Section>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Section title="Definition">
          <Facts
            items={[
              ["Version", `${String(m.version)} (current)`],
              [
                "SHA-256",
                <code key="sha" className="break-all text-xs">
                  {m.sha256}
                </code>,
              ],
              ["Source", `${m.source.collector} / ${m.source.query}`],
              ["Grouped by", m.group_by.length ? m.group_by.map(humanize).join(", ") : "Nothing"],
            ]}
          />
          <div className="mt-3">
            <JsonBlock value={m.definition} label={`${m.id} definition`} />
          </div>
        </Section>
        <div className="space-y-4">
          <Section title="Frameworks and controls">
            <ul className="space-y-1 text-sm">
              {m.frameworks.map((f) => (
                <li key={f.ref}>
                  <span className="font-medium">{f.framework_name}</span>{" "}
                  <span>{f.ref.split(":")[1]}</span>
                  {f.short_title ? `: ${f.short_title}` : ""}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-sm">
              Controls:{" "}
              {m.controls.map((c, i) => (
                <span key={c}>
                  {i > 0 && ", "}
                  <Link to={`/controls/${c}`} className="underline underline-offset-4">
                    {c}
                  </Link>
                </span>
              ))}
            </p>
          </Section>
          <Section title="Version history">
            <ul className="space-y-1 text-sm">
              {m.versions.map((v) => (
                <li key={v.version} className="flex flex-wrap gap-x-3">
                  <span className="font-medium">Version {v.version}</span>
                  <code className="text-xs">{shortHash(v.sha256)}</code>
                  <span className="text-muted-foreground">{formatDate(v.created_at)}</span>
                  {v.current && <span className="text-muted-foreground">current</span>}
                </li>
              ))}
            </ul>
          </Section>
        </div>
      </div>
    </>
  );
}

export function MeasurementPage({ id }: { id: string }) {
  const measurement = useMeasurement(id);
  if (measurement.isError) return <ErrorState error={measurement.error} />;
  if (!measurement.data) return <Loading what="the measurement" />;
  const d = measurement.data;
  const dims = Object.entries(d.dimensions);
  return (
    <>
      <PageHeader
        title={`Measurement ${id}`}
        lead={
          <>
            <Link to={`/metrics/${d.metric_id}`} className="underline underline-offset-4">
              {d.metric_id} {d.metric_name}
            </Link>{" "}
            on {formatDate(d.point.as_of)}
            {dims.length ? `, ${dims.map(([, v]) => v).join(", ")}` : ", overall"}
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Result">
          <div className="mb-3 flex items-baseline gap-3">
            <span className="text-3xl font-semibold tabular">{d.point.value ?? "No value"}</span>
            <StatusBadge status={d.point.status} />
          </div>
          <Facts
            items={[
              ["Definition version", String(d.point.definition_version)],
              [
                "Definition SHA-256",
                <code key="d" className="break-all text-xs">
                  {d.definition_sha256}
                </code>,
              ],
              ["Computed", formatDate(d.computed_at)],
              ["Change vs last period", d.point.delta_previous ?? "—"],
              ["Change vs baseline", d.point.delta_baseline ?? "—"],
              ["Distance to target", d.point.distance_to_target ?? "—"],
            ]}
          />
        </Section>
        <Section title="Calculation">
          <JsonBlock value={d.calculation} label="Calculation record" />
        </Section>
      </div>
      <div className="mt-4">
        <Section title="Source batches">
          {d.batches.length === 0 && d.missing_batches.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No input batches: the status is unknown because nothing was collected.
            </p>
          )}
          <ul className="space-y-3">
            {d.batches.map((b) => (
              <li key={b.sha256} className="rounded-lg border-[0.5px] border-border p-3 text-sm">
                <Link
                  to={`/batches/${b.sha256}`}
                  className="font-medium underline underline-offset-4"
                >
                  {b.instance_id} / {b.query}
                </Link>
                <p className="mt-1 text-muted-foreground">
                  {b.record_count} records collected {formatDate(b.collected_at)} by {b.collector}{" "}
                  {b.collector_version}
                </p>
                <code className="mt-1 block break-all text-xs">{b.sha256}</code>
              </li>
            ))}
            {d.missing_batches.map((h) => (
              <li key={h} className="text-sm text-muted-foreground">
                Batch <code className="text-xs">{h}</code> is no longer stored (retention).
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </>
  );
}

const PAGE = 50;

export function BatchPage({ sha256, offset }: { sha256: string; offset: number }) {
  const batch = useBatch(sha256, offset, PAGE);
  if (batch.isError) return <ErrorState error={batch.error} />;
  if (!batch.data) return <Loading what="the batch" />;
  const { batch: b, records, total } = batch.data;
  const columns = [...new Set(records.flatMap((r) => Object.keys(r)))];
  const dropped = Object.entries(b.redaction.fields_dropped ?? {});
  const pageLink = (o: number) => `/batches/${sha256}?offset=${String(o)}`;
  return (
    <>
      <PageHeader
        title={`${b.instance_id} / ${b.query}`}
        lead={`Record batch collected ${formatDate(b.collected_at)} for ${formatDate(b.as_of)}.`}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Provenance">
          <Facts
            items={[
              [
                "SHA-256",
                <code key="s" className="break-all text-xs">
                  {b.sha256}
                </code>,
              ],
              ["Collector", `${b.collector} ${b.collector_version}`],
              ["Instance", b.instance_id],
              ["Query", b.query],
              ["Parameters", JSON.stringify(b.params)],
              ["Records", String(b.record_count)],
              ["Stored", b.storage_ref],
            ]}
          />
        </Section>
        <Section title="Redaction">
          <Facts
            items={[
              ["Card numbers masked", String(b.redaction.pans_masked ?? 0)],
              [
                "Fields dropped",
                dropped.length ? dropped.map(([f, n]) => `${f} (${String(n)})`).join(", ") : "None",
              ],
            ]}
          />
          <p className="mt-3 text-sm text-muted-foreground">
            The hash covers the records exactly as shown here, after redaction.
          </p>
        </Section>
      </div>
      <div className="mt-4">
        <Section
          title="Records"
          actions={
            <div className="flex items-center gap-2 text-sm" data-print="hide">
              <span className="text-muted-foreground tabular">
                {offset + 1} to {Math.min(offset + PAGE, total)} of {total}
              </span>
              <Button asChild variant="outline" size="sm">
                <Link
                  to={pageLink(Math.max(0, offset - PAGE))}
                  aria-disabled={offset === 0}
                  className={offset === 0 ? "pointer-events-none opacity-50" : ""}
                >
                  Previous
                </Link>
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link
                  to={pageLink(offset + PAGE)}
                  aria-disabled={offset + PAGE >= total}
                  className={offset + PAGE >= total ? "pointer-events-none opacity-50" : ""}
                >
                  Next
                </Link>
              </Button>
            </div>
          }
        >
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Batch records">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  {columns.map((c) => (
                    <th key={c} scope="col" className="whitespace-nowrap px-2 py-1 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.map((r, i) => (
                  <tr key={offset + i} className="border-t-[0.5px] border-border">
                    {columns.map((c) => (
                      <td key={c} className="whitespace-nowrap px-2 py-1">
                        {r[c] === undefined || r[c] === null
                          ? ""
                          : typeof r[c] === "object"
                            ? JSON.stringify(r[c])
                            : String(r[c] as string | number | boolean)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </div>
    </>
  );
}
