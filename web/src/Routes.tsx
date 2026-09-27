import { EmptyState, PageHeader } from "@/components/States";
import { match, useLocation } from "@/lib/router";
import { ControlDetailPage, ControlsPage } from "@/pages/ControlPages";
import { DashboardPage } from "@/pages/DashboardPage";
import { BatchPage, MeasurementPage, MetricDetailPage, MetricsPage } from "@/pages/MetricPages";
import { Overview } from "@/pages/Overview";
import { ExceptionsPage, FindingsPage } from "@/pages/RegisterPages";
import { AuditLogPage, AuditRoomPage, ReportsPage } from "@/pages/ReportPages";

/**
 * Maps the current path to a screen. Keys force a fresh screen when the id changes.
 * Auditors are not staff: they get the audit room and nothing else.
 */
export function Routes({ staff = true }: { staff?: boolean }) {
  const { path, search } = useLocation();
  let p: Record<string, string> | null;

  if (path === "/audit-room") return <AuditRoomPage />;
  if (!staff) return <AuditRoomPage />;
  if (path === "/reports") return <ReportsPage />;
  if (path === "/audit-log") return <AuditLogPage />;
  if (path === "/") return <Overview />;
  if ((p = match("/dashboards/:id", path))) return <DashboardPage key={p.id} id={p.id ?? ""} />;
  if (path === "/metrics") return <MetricsPage />;
  if ((p = match("/metrics/:id", path))) return <MetricDetailPage key={p.id} id={p.id ?? ""} />;
  if ((p = match("/measurements/:id", path))) {
    return <MeasurementPage key={p.id} id={p.id ?? ""} />;
  }
  if ((p = match("/batches/:sha", path))) {
    const offset = Math.max(0, Number.parseInt(search.get("offset") ?? "0", 10) || 0);
    return <BatchPage key={p.sha} sha256={p.sha ?? ""} offset={offset} />;
  }
  if (path === "/controls") return <ControlsPage />;
  if ((p = match("/controls/:id", path))) return <ControlDetailPage key={p.id} id={p.id ?? ""} />;
  if (path === "/exceptions") return <ExceptionsPage />;
  if (path === "/findings") return <FindingsPage />;
  return (
    <>
      <PageHeader title="Page not found" />
      <EmptyState title="There is nothing at this address">
        Use the navigation above to find a dashboard, metric or control.
      </EmptyState>
    </>
  );
}
