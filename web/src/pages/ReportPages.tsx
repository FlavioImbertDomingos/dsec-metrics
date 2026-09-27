import { Download, FileCheck2, Link2, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ApiError, abilities } from "@/api/client";
import {
  type ReportForm,
  useAuditEvents,
  useAuditRoom,
  useAuditVerify,
  useCreateLink,
  useCreateReport,
  usePublicKey,
  useReports,
} from "@/api/hooks";
import type { AuditEvent, ReportPackage } from "@/api/types";
import { useMe } from "@/auth/session";
import { DataTable } from "@/components/DataTable";
import { Facts, Section } from "@/components/Details";
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/States";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDate, humanize, shortHash } from "@/lib/format";

const TYPES = [
  { value: "control", label: "Control evidence package" },
  { value: "framework", label: "Framework period report" },
  { value: "reproducibility", label: "Metric reproducibility report" },
  { value: "risk_committee", label: "Risk committee pack" },
  { value: "management", label: "Management report" },
  { value: "exceptions", label: "Exceptions register export" },
];

const TYPE_LABEL: Record<string, string> = Object.fromEntries(TYPES.map((t) => [t.value, t.label]));

function kb(size: number): string {
  return `${String(Math.max(1, Math.round(size / 1024)))} KB`;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503)
      return "Report signing is not set up on this server. Run make signing-key.";
    if (error.status === 403) return "Your role cannot do this.";
    return error.message;
  }
  return "Something went wrong. Try again.";
}

function SelectField({
  id,
  label,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  type = "text",
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

function GenerateForm() {
  const create = useCreateReport();
  const [form, setForm] = useState({
    report_type: "control",
    period_start: "2026-07-01",
    period_end: "2026-09-30",
    control_id: "DS-SM-02",
    framework: "pci-dss-4.0.1",
    requirements: "3, 8",
    metric_id: "KRI-06",
    prepared_for: "",
  });
  const set = (key: keyof typeof form) => (value: string) => {
    setForm({ ...form, [key]: value });
  };
  const submit = () => {
    const body: ReportForm = {
      report_type: form.report_type,
      period_start: form.period_start,
      period_end: form.period_end,
      prepared_for: form.prepared_for,
    };
    if (form.report_type === "control") body.control_id = form.control_id.trim();
    if (form.report_type === "framework") {
      body.framework = form.framework.trim();
      body.requirements = form.requirements
        .split(",")
        .map((r) => r.trim())
        .filter(Boolean);
    }
    if (form.report_type === "reproducibility") body.metric_id = form.metric_id.trim();
    create.mutate(body);
  };
  return (
    <Section title="Generate a package">
      <form
        className="grid gap-4 md:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <SelectField
          id="report-type"
          label="Report type"
          value={form.report_type}
          onChange={set("report_type")}
          options={TYPES}
        />
        <TextField
          id="period-start"
          label="Period start"
          type="date"
          value={form.period_start}
          onChange={set("period_start")}
        />
        <TextField
          id="period-end"
          label="Period end"
          type="date"
          value={form.period_end}
          onChange={set("period_end")}
        />
        {form.report_type === "control" && (
          <TextField
            id="control-id"
            label="Control"
            value={form.control_id}
            onChange={set("control_id")}
          />
        )}
        {form.report_type === "framework" && (
          <>
            <TextField
              id="framework"
              label="Framework pack"
              value={form.framework}
              onChange={set("framework")}
            />
            <TextField
              id="requirements"
              label="Requirements"
              value={form.requirements}
              onChange={set("requirements")}
              hint="Ids or prefixes, separated by commas. Empty means all."
            />
          </>
        )}
        {form.report_type === "reproducibility" && (
          <TextField
            id="metric-id"
            label="Metric"
            value={form.metric_id}
            onChange={set("metric_id")}
          />
        )}
        <TextField
          id="prepared-for"
          label="Prepared for"
          value={form.prepared_for}
          onChange={set("prepared_for")}
        />
        <div className="flex items-end gap-3 md:col-span-3">
          <Button type="submit" disabled={create.isPending}>
            <FileCheck2 aria-hidden="true" />
            {create.isPending ? "Building…" : "Build and sign"}
          </Button>
          <div aria-live="polite" className="text-sm">
            {create.isError && (
              <span role="alert" className="text-danger">
                {errorText(create.error)}
              </span>
            )}
            {create.data && (
              <span>
                Built {create.data.title} ({kb(create.data.size)}).{" "}
                <a
                  href={`/api/reports/${create.data.id}/download`}
                  className="underline underline-offset-4"
                >
                  Download it
                </a>
              </span>
            )}
          </div>
        </div>
      </form>
    </Section>
  );
}

function LinkForm({ pkg }: { pkg: ReportPackage }) {
  const link = useCreateLink(pkg.id);
  const [username, setUsername] = useState("");
  const [days, setDays] = useState("7");
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        link.mutate({ username: username.trim(), days: Number(days) || 7 });
      }}
    >
      <TextField
        id={`auditor-${pkg.id}`}
        label="Auditor username"
        value={username}
        onChange={setUsername}
      />
      <TextField id={`days-${pkg.id}`} label="Days" type="number" value={days} onChange={setDays} />
      <Button
        type="submit"
        variant="outline"
        size="sm"
        disabled={link.isPending || !username.trim()}
      >
        <Link2 aria-hidden="true" />
        Create link
      </Button>
      <div aria-live="polite" className="basis-full text-sm">
        {link.isError && (
          <span role="alert" className="text-danger">
            {errorText(link.error)}
          </span>
        )}
        {link.data && (
          <span>
            Link for {link.data.username}, valid until {formatDate(link.data.expires_at)}. Copy it
            now; it is not shown again:{" "}
            <code className="break-all text-xs">{window.location.origin + link.data.url}</code>
          </span>
        )}
      </div>
    </form>
  );
}

function PackagesTable({ packages, canLink }: { packages: ReportPackage[]; canLink: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <DataTable<ReportPackage>
      caption="Report packages"
      data={packages}
      rowKey={(p) => p.id}
      columns={[
        {
          id: "title",
          header: "Report",
          accessorFn: (p) => p.title,
          cell: ({ row }) => (
            <div>
              <p className="font-medium">{row.original.title}</p>
              <p className="text-xs text-muted-foreground">
                {TYPE_LABEL[row.original.report_type] ?? row.original.report_type},{" "}
                {row.original.pdf_rendered ? "PDF" : "HTML report"}, {kb(row.original.size)}
              </p>
              {canLink && open === row.original.id && (
                <div className="mt-2">
                  <LinkForm pkg={row.original} />
                </div>
              )}
            </div>
          ),
        },
        {
          id: "period",
          header: "Period",
          accessorFn: (p) => p.period_end,
          cell: ({ row }) =>
            `${formatDate(row.original.period_start)} to ${formatDate(row.original.period_end)}`,
        },
        { id: "frameworks", header: "Frameworks", accessorFn: (p) => p.frameworks.join(", ") },
        {
          id: "generated",
          header: "Generated",
          accessorFn: (p) => p.generated_at,
          cell: ({ row }) =>
            `${formatDate(row.original.generated_at)} by ${row.original.generated_by}`,
        },
        {
          id: "manifest",
          header: "Manifest SHA-256",
          enableSorting: false,
          cell: ({ row }) => (
            <code className="text-xs">{shortHash(row.original.manifest_sha256)}</code>
          ),
        },
        {
          id: "actions",
          header: "Actions",
          enableSorting: false,
          cell: ({ row }) => (
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="outline" size="sm">
                <a href={`/api/reports/${row.original.id}/download`} download>
                  <Download aria-hidden="true" />
                  Download
                </a>
              </Button>
              {canLink && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-expanded={open === row.original.id}
                  onClick={() => {
                    setOpen(open === row.original.id ? null : row.original.id);
                  }}
                >
                  <Link2 aria-hidden="true" />
                  Auditor link
                </Button>
              )}
            </div>
          ),
        },
      ]}
    />
  );
}

function VerifyHelp() {
  const key = usePublicKey();
  return (
    <Section title="Verifying a package">
      <p className="text-sm">
        Each ZIP holds a manifest with the SHA-256 of every file and an Ed25519 signature over the
        manifest. Anyone can check it without access to this system:
      </p>
      <pre
        role="region"
        aria-label="Verify command"
        tabIndex={0}
        className="mt-2 overflow-x-auto rounded-lg bg-surface-muted p-3 text-xs"
      >
        dsec-metrics verify package.zip --fingerprint {key.data?.fingerprint ?? "<fingerprint>"}
      </pre>
      {key.data ? (
        <div className="mt-3">
          <Facts
            items={[
              ["Algorithm", key.data.algorithm],
              [
                "Key fingerprint",
                <code key="f" className="break-all text-xs">
                  {key.data.fingerprint}
                </code>,
              ],
            ]}
          />
        </div>
      ) : (
        key.isError && <p className="mt-2 text-sm text-muted-foreground">{errorText(key.error)}</p>
      )}
    </Section>
  );
}

export function ReportsPage() {
  const me = useMe();
  const reports = useReports();
  const can = abilities({ roles: me.data?.roles ?? [] });
  if (reports.isError) return <ErrorState error={reports.error} />;
  if (!reports.data) return <Loading what="reports" />;
  return (
    <>
      <PageHeader
        title="Reports"
        lead="Signed evidence packages built from stored measurements, batches and registers."
      />
      <div className="grid gap-4">
        {can.author && <GenerateForm />}
        <Section title="Packages">
          {reports.data.length === 0 ? (
            <EmptyState title="No packages yet">
              {can.author ? "Build one with the form above." : "Ask a reviewer to build one."}
            </EmptyState>
          ) : (
            <PackagesTable packages={reports.data} canLink={can.author} />
          )}
        </Section>
        <VerifyHelp />
      </div>
    </>
  );
}

function AccessLog({ events }: { events: AuditEvent[] }) {
  if (events.length === 0)
    return <p className="text-sm text-muted-foreground">No downloads yet.</p>;
  return (
    <DataTable<AuditEvent>
      caption="Access log"
      data={events}
      rowKey={(e) => String(e.seq)}
      columns={[
        {
          id: "when",
          header: "When",
          accessorFn: (e) => e.occurred_at,
          cell: ({ row }) => formatDate(row.original.occurred_at),
        },
        { id: "who", header: "Who", accessorFn: (e) => e.actor },
        {
          id: "what",
          header: "Package",
          accessorFn: (e) => e.target.replace("report:", "").slice(0, 8),
        },
        {
          id: "via",
          header: "Via",
          accessorFn: (e) =>
            (typeof e.details.via === "string" ? e.details.via.split(":")[0] : "") ?? "",
        },
        { id: "seq", header: "Log entry", accessorFn: (e) => e.seq },
      ]}
    />
  );
}

export function AuditRoomPage() {
  const room = useAuditRoom();
  if (room.isError) return <ErrorState error={room.error} />;
  if (!room.data) return <Loading what="the audit room" />;
  const d = room.data;
  return (
    <>
      <PageHeader
        title="Audit room"
        lead={
          d.auditor
            ? "The packages your grant covers. Every download is recorded."
            : "What auditors can see, and every package download."
        }
      />
      <div className="grid gap-4">
        <Section title={d.auditor ? "Your access" : "Auditor grants"}>
          {d.grants.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {d.auditor
                ? "You have no current grant. Ask the compliance team for access."
                : "No auditor grants."}
            </p>
          ) : (
            <ul className="space-y-1 text-sm">
              {d.grants.map((g) => (
                <li key={g.id}>
                  {!d.auditor && <span className="font-medium">{g.username}: </span>}
                  {g.frameworks.join(", ")} for {formatDate(g.period_start)} to{" "}
                  {formatDate(g.period_end)}, until {formatDate(g.expires_at)}
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Packages">
          {d.packages.length === 0 ? (
            <EmptyState title="No packages to show" />
          ) : (
            <PackagesTable packages={d.packages} canLink={false} />
          )}
        </Section>
        <VerifyHelp />
        <Section title="Access log">
          <AccessLog events={d.access_log} />
        </Section>
      </div>
    </>
  );
}

export function AuditLogPage() {
  const [before, setBefore] = useState<number | undefined>(undefined);
  const [action, setAction] = useState("");
  const events = useAuditEvents(before, action || undefined);
  const verify = useAuditVerify();
  if (events.isError) return <ErrorState error={events.error} />;
  if (!events.data) return <Loading what="the audit log" />;
  const last = events.data.at(-1);
  return (
    <>
      <PageHeader
        title="Audit log"
        lead="Append-only. Each entry carries the hash of the one before it."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void verify.refetch();
            }}
          >
            <ShieldCheck aria-hidden="true" />
            Verify chain
          </Button>
        }
      />
      <div aria-live="polite" className="mb-4 text-sm">
        {verify.data &&
          (verify.data.ok ? (
            <p className="text-status-green">
              Chain intact: {verify.data.checked} entries, head {shortHash(verify.data.head)}.
            </p>
          ) : (
            <p role="alert" className="text-status-red">
              Chain broken at entry {verify.data.broken_at}: {verify.data.reason}.
            </p>
          ))}
      </div>
      <div className="mb-4 flex items-end gap-2">
        <SelectField
          id="audit-action"
          label="Action"
          value={action}
          onChange={(v) => {
            setAction(v);
            setBefore(undefined);
          }}
          options={[
            { value: "", label: "All" },
            ...[
              "auth.login",
              "auth.failed",
              "auth.logout",
              "definition.version",
              "collection.run",
              "report.generate",
              "report.download",
              "report.link",
              "auditor.grant",
            ].map((a) => ({ value: a, label: a })),
          ]}
        />
      </div>
      <Section title="Entries">
        <DataTable<AuditEvent>
          caption="Audit log entries"
          data={events.data}
          rowKey={(e) => String(e.seq)}
          columns={[
            { id: "seq", header: "#", accessorFn: (e) => e.seq },
            {
              id: "when",
              header: "When",
              accessorFn: (e) => e.occurred_at,
              cell: ({ row }) =>
                new Date(row.original.occurred_at).toISOString().replace("T", " ").slice(0, 19),
            },
            { id: "actor", header: "Actor", accessorFn: (e) => e.actor },
            { id: "action", header: "Action", accessorFn: (e) => humanize(e.action) },
            { id: "target", header: "Target", accessorFn: (e) => e.target },
            {
              id: "hash",
              header: "Hash",
              enableSorting: false,
              cell: ({ row }) => <code className="text-xs">{shortHash(row.original.hash)}</code>,
            },
          ]}
        />
        {last && last.seq > 1 && (
          <div className="mt-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setBefore(last.seq);
              }}
            >
              Older entries
            </Button>
          </div>
        )}
      </Section>
    </>
  );
}
