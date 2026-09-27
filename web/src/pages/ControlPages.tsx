import { useControl, useControls } from "@/api/hooks";
import type { ControlSummary } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { Facts, Section } from "@/components/Details";
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/States";
import { StatusBadge } from "@/components/Status";
import { formatDate, humanize, shortHash } from "@/lib/format";
import { Link } from "@/lib/router";
import { ExceptionsTable, FindingsTable } from "@/pages/RegisterPages";
import { MetricLink, ValueLink } from "@/widgets/common";

const RANK = { red: 0, amber: 1, unknown: 2, green: 3 };

export function ControlsPage() {
  const controls = useControls();
  if (controls.isError) return <ErrorState error={controls.error} />;
  if (!controls.data) return <Loading what="controls" />;
  return (
    <>
      <PageHeader
        title="Controls"
        lead="Status is the worst status of the control's metrics. Unknown ranks above green."
      />
      <div className="rounded-card border-[0.5px] border-border bg-surface p-4">
        <DataTable<ControlSummary>
          caption="Controls"
          data={controls.data}
          rowKey={(c) => c.id}
          initialSort={[{ id: "status", desc: false }]}
          columns={[
            {
              id: "control",
              header: "Control",
              accessorFn: (c) => c.id,
              cell: ({ row }) => (
                <Link
                  to={`/controls/${row.original.id}`}
                  className="underline-offset-4 hover:underline"
                >
                  <span className="font-medium">{row.original.id}</span> {row.original.name}
                </Link>
              ),
            },
            {
              id: "status",
              header: "Status",
              accessorFn: (c) => RANK[c.status],
              cell: ({ row }) => <StatusBadge status={row.original.status} />,
            },
            { id: "owner", header: "Owner", accessorFn: (c) => humanize(c.owner) },
            { id: "metrics", header: "Metrics", accessorFn: (c) => c.metric_ids.join(", ") },
            { id: "exceptions", header: "Open exceptions", accessorFn: (c) => c.open_exceptions },
            { id: "findings", header: "Open findings", accessorFn: (c) => c.open_findings },
          ]}
        />
      </div>
    </>
  );
}

export function ControlDetailPage({ id }: { id: string }) {
  const control = useControl(id);
  if (control.isError) return <ErrorState error={control.error} />;
  if (!control.data) return <Loading what="the control" />;
  const c = control.data;
  return (
    <>
      <PageHeader
        title={
          <>
            <span>{c.id}</span> {c.name}
          </>
        }
        lead={c.description || undefined}
        actions={<StatusBadge status={c.status} />}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Requirements">
          <ul className="space-y-1 text-sm">
            {c.requirements.map((r) => (
              <li key={r.ref}>
                <span className="font-medium">{r.framework_name}</span>{" "}
                <span>{r.ref.split(":")[1]}</span>
                {r.short_title ? `: ${r.short_title}` : ""}
              </li>
            ))}
          </ul>
          <div className="mt-3">
            <Facts items={[["Owner", humanize(c.owner)]]} />
          </div>
        </Section>
        <Section title="Metrics">
          {c.metrics.length === 0 ? (
            <p className="text-sm text-muted-foreground">No metrics measure this control yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {c.metrics.map((m) => (
                <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <StatusBadge status={m.latest?.status ?? "unknown"} />
                  <MetricLink metric={m} />
                  <ValueLink point={m.latest} metric={m} className="ml-auto font-semibold" />
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <div className="mt-4">
        <Section title="Evidence">
          {c.evidence.length === 0 ? (
            <p className="text-sm text-muted-foreground">No evidence sources configured.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {c.evidence.map((e) => (
                <li key={`${e.collector}/${e.query}`} className="flex flex-wrap gap-x-3">
                  <span className="font-medium">
                    {e.collector} / {e.query}
                  </span>
                  <span className="text-muted-foreground">kept {e.retain_days} days</span>
                  {e.latest ? (
                    <Link
                      to={`/batches/${e.latest.sha256}`}
                      className="underline underline-offset-4"
                    >
                      Latest batch {shortHash(e.latest.sha256)}, {formatDate(e.latest.collected_at)}
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">Not collected yet</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <div className="mt-4 grid gap-4">
        <Section title="Exceptions">
          {c.exceptions.length ? (
            <ExceptionsTable items={c.exceptions} caption={`Exceptions for ${c.id}`} />
          ) : (
            <EmptyState title="No exceptions for this control" />
          )}
        </Section>
        <Section title="Findings">
          {c.findings.length ? (
            <FindingsTable items={c.findings} caption={`Findings for ${c.id}`} />
          ) : (
            <EmptyState title="No findings for this control" />
          )}
        </Section>
      </div>
    </>
  );
}
