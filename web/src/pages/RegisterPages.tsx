import { useExceptions, useFindings } from "@/api/hooks";
import type { Dimensions, ExceptionItem, FindingItem, Register } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { Section } from "@/components/Details";
import { FilterBar } from "@/components/FilterBar";
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/States";
import { DIMENSIONS, useFilters } from "@/lib/filters";
import { formatDate, humanize, shortHash } from "@/lib/format";
import { Link, useLocation } from "@/lib/router";
import { cn } from "@/lib/utils";

function dimensionOptions(items: Dimensions[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const dim of DIMENSIONS) {
    const values = [...new Set(items.map((i) => i[dim]).filter((v): v is string => !!v))];
    if (values.length > 1) out[dim] = values.sort();
  }
  return out;
}

function SourceNote({ register }: { register: Register<unknown> }) {
  if (!register.source) return null;
  return (
    <p className="mb-4 text-sm text-muted-foreground">
      From batch{" "}
      <Link to={`/batches/${register.source.sha256}`} className="underline underline-offset-4">
        {shortHash(register.source.sha256)}
      </Link>
      , collected {formatDate(register.source.collected_at)}. Ages are counted to{" "}
      {formatDate(register.source.as_of)}.
      {register.skipped > 0 && ` ${String(register.skipped)} records were skipped as invalid.`}
    </p>
  );
}

function Expiry({ days }: { days: number | null }) {
  if (days === null) return <span className="text-muted-foreground">No expiry</span>;
  if (days < 0) return <span className="text-status-red">Expired {-days} days ago</span>;
  return <span className={cn(days <= 30 && "text-status-amber")}>In {days} days</span>;
}

export function ExceptionsTable({ items, caption }: { items: ExceptionItem[]; caption: string }) {
  return (
    <DataTable<ExceptionItem>
      caption={caption}
      data={items}
      rowKey={(e) => e.exception_id}
      initialSort={[{ id: "age", desc: true }]}
      columns={[
        { id: "id", header: "Exception", accessorFn: (e) => e.exception_id },
        {
          id: "control",
          header: "Control",
          accessorFn: (e) => e.control_id ?? "",
          cell: ({ row }) =>
            row.original.control_id ? (
              <Link to={`/controls/${row.original.control_id}`} className="hover:underline">
                {row.original.control_id}
              </Link>
            ) : null,
        },
        { id: "status", header: "Status", accessorFn: (e) => humanize(e.status) },
        { id: "risk", header: "Risk", accessorFn: (e) => humanize(e.risk_rating ?? "") },
        { id: "unit", header: "Business unit", accessorFn: (e) => e.business_unit ?? "" },
        { id: "age", header: "Age (days)", accessorFn: (e) => e.age_days ?? -1 },
        {
          id: "expiry",
          header: "Expiry",
          accessorFn: (e) => e.days_to_expiry ?? Infinity,
          cell: ({ row }) => <Expiry days={row.original.days_to_expiry} />,
        },
        { id: "cause", header: "Root cause", accessorFn: (e) => humanize(e.root_cause ?? "") },
        { id: "owner", header: "Owner", accessorFn: (e) => e.owner ?? "" },
      ]}
    />
  );
}

export function FindingsTable({ items, caption }: { items: FindingItem[]; caption: string }) {
  const rank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  return (
    <DataTable<FindingItem>
      caption={caption}
      data={items}
      rowKey={(f) => f.finding_id}
      initialSort={[{ id: "past_due", desc: true }]}
      columns={[
        { id: "id", header: "Finding", accessorFn: (f) => f.finding_id },
        {
          id: "severity",
          header: "Severity",
          accessorFn: (f) => rank[f.severity] ?? 9,
          cell: ({ row }) => humanize(row.original.severity),
        },
        { id: "status", header: "Status", accessorFn: (f) => humanize(f.status) },
        {
          id: "control",
          header: "Control",
          accessorFn: (f) => f.control_id ?? "",
          cell: ({ row }) =>
            row.original.control_id ? (
              <Link to={`/controls/${row.original.control_id}`} className="hover:underline">
                {row.original.control_id}
              </Link>
            ) : null,
        },
        { id: "source", header: "Source", accessorFn: (f) => humanize(f.source ?? "") },
        {
          id: "due",
          header: "Due",
          accessorFn: (f) => f.due_date ?? "",
          cell: ({ row }) => formatDate(row.original.due_date),
        },
        { id: "past_due", header: "Days past due", accessorFn: (f) => f.days_past_due ?? 0 },
        { id: "repeat", header: "Repeat", accessorFn: (f) => (f.repeat ? "Yes" : "No") },
      ]}
    />
  );
}

function Tally({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-card border-[0.5px] border-border bg-surface px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-2xl font-semibold tabular", tone)}>{value}</p>
    </div>
  );
}

const MONTH = new Intl.DateTimeFormat("en", { month: "long", year: "numeric", timeZone: "UTC" });

export function ExceptionsPage() {
  const [filters, setFilters] = useFilters();
  const all = useExceptions({});
  const register = useExceptions(filters);
  if (register.isError) return <ErrorState error={register.error} />;
  if (!register.data || !all.data) return <Loading what="the exceptions register" />;
  const items = register.data.items;
  const open = items.filter(
    (e) => !["closed", "rejected", "withdrawn", "revoked"].includes(e.status),
  );
  const causes = new Map<string, number>();
  for (const e of open)
    causes.set(e.root_cause ?? "unknown", (causes.get(e.root_cause ?? "unknown") ?? 0) + 1);
  const maxCause = Math.max(1, ...causes.values());
  const upcoming = open
    .filter(
      (e) =>
        e.expires_at &&
        e.days_to_expiry !== null &&
        e.days_to_expiry >= 0 &&
        e.days_to_expiry <= 180,
    )
    .sort((a, b) => (a.days_to_expiry ?? 0) - (b.days_to_expiry ?? 0));
  const byMonth = new Map<string, ExceptionItem[]>();
  for (const e of upcoming) {
    const key = MONTH.format(new Date(`${e.expires_at ?? ""}T00:00:00Z`));
    byMonth.set(key, [...(byMonth.get(key) ?? []), e]);
  }

  return (
    <>
      <PageHeader
        title="Exceptions"
        lead="Approved deviations from controls, read from the GRC tool."
      />
      <FilterBar
        options={dimensionOptions(all.data.items)}
        filters={filters}
        onChange={setFilters}
      />
      <SourceNote register={register.data} />
      {items.length === 0 ? (
        <EmptyState title="No exceptions match">
          Clear the filters, or check that the exceptions register source is collecting.
        </EmptyState>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-4">
            <Tally label="Open" value={open.length} />
            <Tally
              label="Open more than 180 days"
              value={open.filter((e) => (e.age_days ?? 0) > 180).length}
              tone="text-status-amber"
            />
            <Tally
              label="Expiring within 30 days"
              value={
                open.filter(
                  (e) =>
                    e.days_to_expiry !== null && e.days_to_expiry >= 0 && e.days_to_expiry <= 30,
                ).length
              }
            />
            <Tally
              label="Past expiry"
              value={open.filter((e) => (e.days_to_expiry ?? 0) < 0).length}
              tone="text-status-red"
            />
          </div>
          <div className="mb-4 grid gap-4 lg:grid-cols-2">
            <Section title="Root causes">
              <ul className="space-y-2 text-sm">
                {[...causes.entries()]
                  .sort((a, b) => b[1] - a[1])
                  .map(([cause, n]) => (
                    <li key={cause} className="grid grid-cols-[10rem_1fr_2rem] items-center gap-2">
                      <span>{humanize(cause)}</span>
                      <span className="h-2 rounded-full bg-surface-muted" aria-hidden="true">
                        <span
                          className="block h-2 rounded-full bg-accent"
                          style={{ width: `${String((n / maxCause) * 100)}%` }}
                        />
                      </span>
                      <span className="text-right tabular">{n}</span>
                    </li>
                  ))}
              </ul>
            </Section>
            <Section title="Expiry calendar">
              {byMonth.size === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Nothing expires in the next 180 days.
                </p>
              ) : (
                <div className="space-y-3 text-sm">
                  {[...byMonth.entries()].map(([month, list]) => (
                    <div key={month}>
                      <h3 className="font-medium">{month}</h3>
                      <ul className="mt-1 space-y-0.5 text-muted-foreground">
                        {list.map((e) => (
                          <li key={e.exception_id}>
                            {formatDate(e.expires_at)}: {e.exception_id}
                            {e.control_id ? ` (${e.control_id})` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          </div>
          <Section title="Register">
            <ExceptionsTable items={items} caption="Exceptions register" />
          </Section>
        </>
      )}
    </>
  );
}

export function FindingsPage() {
  const [filters, setFilters] = useFilters();
  const { search } = useLocation();
  const severity = search.get("severity") ?? undefined;
  const all = useFindings({});
  const register = useFindings({ ...filters, severity });
  if (register.isError) return <ErrorState error={register.error} />;
  if (!register.data || !all.data) return <Loading what="the findings register" />;
  return (
    <>
      <PageHeader
        title={severity ? `${humanize(severity)} findings` : "Findings"}
        lead="Issues raised by audits and assessments, read from the GRC tool."
      />
      <FilterBar
        options={dimensionOptions(all.data.items)}
        filters={filters}
        onChange={setFilters}
      />
      <SourceNote register={register.data} />
      {register.data.items.length === 0 ? (
        <EmptyState title="No findings match" />
      ) : (
        <Section title="Register">
          <FindingsTable items={register.data.items} caption="Findings register" />
        </Section>
      )}
    </>
  );
}
