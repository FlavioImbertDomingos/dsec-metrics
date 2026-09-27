import { useDashboards, useMetrics } from "@/api/hooks";
import type { MetricSummary, Status } from "@/api/types";
import { EmptyState, ErrorState, Loading, PageHeader, Skeleton } from "@/components/States";
import { StatusBadge } from "@/components/Status";
import { formatDate, humanize } from "@/lib/format";
import { Link } from "@/lib/router";
import { MetricLink, ValueLink } from "@/widgets/common";

const ORDER: Status[] = ["red", "amber", "unknown", "green"];

function counts(metrics: MetricSummary[]): Record<Status, number> {
  const out: Record<Status, number> = { red: 0, amber: 0, unknown: 0, green: 0 };
  for (const m of metrics) out[m.latest?.status ?? "unknown"] += 1;
  return out;
}

/** Audience switcher: one card per dashboard with its status counts, then what is red. */
export function Overview() {
  const dashboards = useDashboards();
  const metrics = useMetrics();

  if (dashboards.isError) return <ErrorState error={dashboards.error} />;
  if (metrics.isError) return <ErrorState error={metrics.error} />;
  if (!dashboards.data || !metrics.data) {
    return (
      <Loading what="the overview">
        <Skeleton className="mb-6 h-8 w-64" />
        <div className="grid gap-4 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      </Loading>
    );
  }

  const all = metrics.data;
  const measured = all.filter((m) => m.latest);
  if (measured.length === 0) {
    return (
      <>
        <PageHeader title="Overview" />
        <EmptyState title="No measurements yet">
          Connect a collector, or load the sample data with{" "}
          <code>docker compose exec api dsec-metrics demo</code>, then reload this page.
        </EmptyState>
      </>
    );
  }
  const asOf = measured
    .map((m) => m.latest?.as_of ?? "")
    .sort()
    .at(-1);
  const attention = all
    .filter((m) => m.latest?.status === "red")
    .sort((a, b) => a.id.localeCompare(b.id));

  return (
    <>
      <PageHeader title="Overview" lead={`Latest measurements as of ${formatDate(asOf)}.`} />
      <nav aria-label="Audiences">
        <ul className="grid gap-4 md:grid-cols-3">
          {dashboards.data.map((d) => {
            const mine = all.filter((m) => m.audience.includes(d.audience));
            const c = counts(mine);
            return (
              <li key={d.id}>
                <Link
                  to={`/dashboards/${d.id}`}
                  className="block h-full rounded-card border-[0.5px] border-border bg-surface p-5 hover:border-foreground/40"
                >
                  <span className="block font-semibold">{d.title}</span>
                  <span className="mt-0.5 block text-sm text-muted-foreground">
                    {mine.length} indicators, refreshed {d.refresh}
                  </span>
                  <span className="mt-3 flex flex-wrap gap-1.5">
                    {ORDER.filter((s) => c[s] > 0).map((s) => (
                      <span key={s} className="inline-flex items-center gap-1 text-sm tabular">
                        <StatusBadge status={s} /> {c[s]}
                      </span>
                    ))}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <section aria-labelledby="attention" className="mt-8">
        <h2 id="attention" className="mb-3 text-base font-semibold">
          Needs attention
        </h2>
        {attention.length === 0 ? (
          <p className="text-sm text-muted-foreground">No indicator is red.</p>
        ) : (
          <ul className="divide-y-[0.5px] divide-border rounded-card border-[0.5px] border-border bg-surface">
            {attention.map((m) => (
              <li key={m.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-4 py-3">
                <StatusBadge status="red" />
                <div className="min-w-0 flex-1">
                  <MetricLink metric={m} />
                  <p className="text-sm text-muted-foreground">
                    Owner {humanize(m.owner)}. {m.action_when_red}
                  </p>
                </div>
                <ValueLink point={m.latest} metric={m} className="font-semibold" />
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
