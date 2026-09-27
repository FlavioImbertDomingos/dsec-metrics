import type { MetricSummary, Point, Series, Widget } from "@/api/types";
import { EChart, useChartTheme } from "@/charts/EChart";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/Status";
import { formatValue } from "@/lib/format";
import { Delta, MetricLink, ValueLink } from "@/widgets/common";

/** One indicator: current value, status, change, and a small trend. */
export function StatWidget({ widget, query }: { widget: Widget; query: string }) {
  const metric = widget.metrics[0];
  if (!metric) return null;
  const point = widget.points[metric.id] ?? null;
  const series = widget.series[0];
  return (
    <div className="flex h-full flex-col gap-2">
      <MetricLink metric={metric} query={query} className="text-sm text-muted-foreground" />
      <div className="flex items-baseline gap-3">
        <ValueLink point={point} metric={metric} className="text-3xl font-semibold" />
        <StatusBadge status={point?.status ?? "unknown"} />
      </div>
      <div className="flex flex-wrap gap-x-3">
        <Delta value={point?.delta_previous} metric={metric} label="vs last period" />
        {metric.target !== null && (
          <span className="text-xs text-muted-foreground">
            Target {formatValue(metric.target, metric.unit)}
          </span>
        )}
      </div>
      {series && series.points.length > 1 && <Sparkline series={series} />}
    </div>
  );
}

function Sparkline({ series }: { series: Series }) {
  const theme = useChartTheme();
  const values = series.points.map((p) => p.value);
  return (
    <div data-print="hide">
      <EChart
        label={`${series.metric.id} over the last ${String(values.length)} periods`}
        height={48}
        option={{
          grid: { left: 2, right: 2, top: 4, bottom: 4 },
          xAxis: { type: "category", show: false, data: series.points.map((p) => p.as_of) },
          yAxis: { type: "value", show: false, scale: true },
          series: [
            {
              type: "line",
              data: values,
              symbol: "none",
              lineStyle: { width: 1.5, color: theme.series[0] },
            },
          ],
        }}
      />
    </div>
  );
}

interface Row {
  metric: MetricSummary;
  point: Point | null;
}

/** Table and RAG list widgets. The RAG list adds owner and action for red items. */
export function MetricTableWidget({ widget, query }: { widget: Widget; query: string }) {
  const rag = widget.widget === "rag_list";
  const rows: Row[] = widget.metrics.map((metric) => ({
    metric,
    point: widget.points[metric.id] ?? null,
  }));
  const rank = { red: 0, amber: 1, unknown: 2, green: 3 };
  return (
    <DataTable<Row>
      caption={widget.title}
      data={rows}
      rowKey={(row) => row.metric.id}
      initialSort={rag ? [{ id: "status", desc: false }] : []}
      columns={[
        {
          id: "metric",
          header: "Indicator",
          accessorFn: (row) => row.metric.id,
          cell: ({ row }) => <MetricLink metric={row.original.metric} query={query} />,
        },
        {
          id: "status",
          header: "Status",
          accessorFn: (row) => rank[row.point?.status ?? "unknown"],
          cell: ({ row }) => <StatusBadge status={row.original.point?.status ?? "unknown"} />,
        },
        {
          id: "value",
          header: "Value",
          accessorFn: (row) => row.point?.value ?? -Infinity,
          cell: ({ row }) => <ValueLink point={row.original.point} metric={row.original.metric} />,
        },
        {
          id: "change",
          header: "Change",
          enableSorting: false,
          cell: ({ row }) => (
            <Delta
              value={row.original.point?.delta_previous}
              metric={row.original.metric}
              label=""
            />
          ),
        },
        ...(rag
          ? [
              {
                id: "owner",
                header: "Owner",
                accessorFn: (row: Row) => row.metric.owner,
              },
              {
                id: "action",
                header: "Action when red",
                enableSorting: false,
                cell: ({ row }: { row: { original: Row } }) =>
                  row.original.point?.status === "red" ? (
                    <span className="text-sm">{row.original.metric.action_when_red}</span>
                  ) : (
                    <span className="text-muted-foreground">None needed</span>
                  ),
              },
            ]
          : [
              {
                id: "target",
                header: "Target",
                accessorFn: (row: Row) => row.metric.target ?? -Infinity,
                cell: ({ row }: { row: { original: Row } }) =>
                  formatValue(row.original.metric.target, row.original.metric.unit),
              },
            ]),
      ]}
    />
  );
}
