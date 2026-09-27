import type { Series, Widget } from "@/api/types";
import { ChartFrame } from "@/charts/ChartFrame";
import { EChart, useChartTheme } from "@/charts/EChart";
import { StatusBadge } from "@/components/Status";
import { formatDate, formatMonth, formatValue, humanize } from "@/lib/format";
import { Link } from "@/lib/router";
import { ValueLink } from "@/widgets/common";

function axisStyle(theme: ReturnType<typeof useChartTheme>) {
  return {
    axisLabel: { color: theme.muted },
    axisLine: { lineStyle: { color: theme.grid } },
    splitLine: { lineStyle: { color: theme.grid } },
  };
}

function tooltip(theme: ReturnType<typeof useChartTheme>) {
  // richText draws the tooltip on the canvas instead of injecting styled HTML.
  return {
    trigger: "axis",
    renderMode: "richText",
    backgroundColor: theme.dark ? "#262626" : "#ffffff",
    borderColor: theme.grid,
    textStyle: { color: theme.text },
  };
}

function trendOption(series: Series[], theme: ReturnType<typeof useChartTheme>) {
  const dates = [...new Set(series.flatMap((s) => s.points.map((p) => p.as_of)))].sort();
  const single = series.length === 1 ? series[0] : undefined;
  const marks: Record<string, unknown>[] = [];
  if (single?.metric.target !== null && single?.metric.target !== undefined) {
    marks.push({ yAxis: single.metric.target, name: "Target" });
  }
  if (single?.baseline !== null && single?.baseline !== undefined) {
    marks.push({ yAxis: single.baseline, name: "Baseline" });
  }
  return {
    color: theme.series,
    tooltip: tooltip(theme),
    legend:
      series.length > 1
        ? { top: 0, textStyle: { color: theme.muted }, data: series.map((s) => s.metric.id) }
        : undefined,
    grid: { left: 48, right: 16, top: series.length > 1 ? 32 : 16, bottom: 28 },
    xAxis: { type: "category", data: dates.map(formatMonth), ...axisStyle(theme) },
    yAxis: {
      type: "value",
      scale: true,
      // Keep the target and baseline lines inside the plotted range.
      min: (v: { min: number }) => Math.min(v.min, ...marks.map((m) => Number(m.yAxis))),
      max: (v: { max: number }) => Math.max(v.max, ...marks.map((m) => Number(m.yAxis))),
      minInterval: series.every((s) => s.metric.unit === "count") ? 1 : undefined,
      ...axisStyle(theme),
    },
    series: series.map((s) => {
      const byDate = new Map(s.points.map((p) => [p.as_of, p.value]));
      return {
        name: s.metric.id,
        type: "line",
        symbolSize: 6,
        data: dates.map((d) => byDate.get(d) ?? null),
        markLine: marks.length
          ? {
              symbol: "none",
              silent: true,
              lineStyle: { type: "dashed", color: theme.muted },
              label: { color: theme.muted, formatter: "{b}", position: "insideEndTop" },
              data: marks,
            }
          : undefined,
      };
    }),
  };
}

/** A table with one row per period and one column per metric; every value links. */
function SeriesTable({ series, caption }: { series: Series[]; caption: string }) {
  const dates = [...new Set(series.flatMap((s) => s.points.map((p) => p.as_of)))].sort();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b-[0.5px] border-border text-left text-xs text-muted-foreground">
            <th scope="col" className="px-2 py-1 font-medium">
              Period
            </th>
            {series.map((s) => (
              <th key={s.metric.id} scope="col" className="px-2 py-1 font-medium">
                {s.metric.id}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dates.map((d) => (
            <tr key={d} className="border-b-[0.5px] border-border last:border-0">
              <th scope="row" className="px-2 py-1 text-left font-normal">
                {formatDate(d)}
              </th>
              {series.map((s) => {
                const point = s.points.find((p) => p.as_of === d) ?? null;
                return (
                  <td key={s.metric.id} className="px-2 py-1">
                    <ValueLink point={point} metric={s.metric} />{" "}
                    {point && <span className="sr-only">{point.status}</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TrendWidget({ widget }: { widget: Widget }) {
  const theme = useChartTheme();
  const names = widget.series.map((s) => s.metric.id).join(" and ");
  const label = `${widget.title}: ${names} over ${String(widget.series[0]?.points.length ?? 0)} periods`;
  return (
    <ChartFrame
      name={widget.title}
      chart={<EChart label={label} option={trendOption(widget.series, theme)} />}
      table={<SeriesTable series={widget.series} caption={widget.title} />}
    />
  );
}

export function BarWidget({ widget }: { widget: Widget }) {
  const theme = useChartTheme();
  const metric = widget.metrics[0];
  if (!metric || widget.cells.length === 0) return null;
  const option = {
    tooltip: { ...tooltip(theme), trigger: "item" },
    grid: { left: 48, right: 16, top: 16, bottom: 28 },
    xAxis: { type: "category", data: widget.cells.map((c) => c.row), ...axisStyle(theme) },
    yAxis: {
      type: "value",
      minInterval: metric.unit === "count" ? 1 : undefined,
      ...axisStyle(theme),
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 48,
        data: widget.cells.map((c) => ({
          value: c.value,
          itemStyle: { color: theme.status[c.status] },
        })),
      },
    ],
  };
  return (
    <ChartFrame
      name={widget.title}
      chart={<EChart label={`${widget.title} by ${widget.rows.join(", ")}`} option={option} />}
      table={
        <table className="w-full text-sm">
          <caption className="sr-only">{widget.title}</caption>
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
            {widget.cells.map((c) => (
              <tr key={c.row} className="border-t-[0.5px] border-border">
                <th scope="row" className="px-2 py-1 text-left font-normal">
                  {c.row}
                </th>
                <td className="px-2 py-1">
                  {c.measurement_id ? (
                    <Link
                      to={`/measurements/${String(c.measurement_id)}`}
                      className="tabular hover:underline"
                    >
                      {formatValue(c.value, metric.unit)}
                    </Link>
                  ) : (
                    formatValue(c.value, metric.unit)
                  )}
                </td>
                <td className="px-2 py-1">
                  <StatusBadge status={c.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  );
}

export function HeatmapWidget({ widget }: { widget: Widget }) {
  const byKey = new Map(widget.cells.map((c) => [`${c.row}|${c.column}`, c]));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{widget.title}</caption>
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <td />
            {widget.columns.map((col) => (
              <th key={col} scope="col" className="px-1 py-1 font-medium">
                {col.startsWith("DS-") ? (
                  <Link to={`/controls/${col}`} className="hover:underline">
                    {col}
                  </Link>
                ) : (
                  <Link to={`/metrics/${col}`} className="hover:underline">
                    {col}
                  </Link>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {widget.rows.map((row) => (
            <tr key={row} className="border-t-[0.5px] border-border">
              <th scope="row" className="py-1 pr-2 text-left font-normal">
                {humanize(row)}
              </th>
              {widget.columns.map((col) => {
                const cell = byKey.get(`${row}|${col}`);
                if (!cell) {
                  return (
                    <td key={col} className="px-1 py-1 text-muted-foreground">
                      —
                    </td>
                  );
                }
                const badge = <StatusBadge status={cell.status} />;
                return (
                  <td key={col} className="px-1 py-1">
                    {cell.measurement_id ? (
                      <Link
                        to={`/measurements/${String(cell.measurement_id)}`}
                        aria-label={`${col} for ${row}: ${cell.status}, open the measurement`}
                        className="rounded-md"
                      >
                        {badge}
                      </Link>
                    ) : (
                      badge
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ExceptionsAgingWidget({ widget }: { widget: Widget }) {
  const theme = useChartTheme();
  const option = {
    tooltip: { ...tooltip(theme), trigger: "item" },
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    xAxis: { type: "category", data: widget.buckets.map((b) => b.label), ...axisStyle(theme) },
    yAxis: { type: "value", minInterval: 1, ...axisStyle(theme) },
    series: [
      {
        type: "bar",
        barMaxWidth: 48,
        data: widget.buckets.map((b) => b.count),
        itemStyle: { color: theme.series[0] },
      },
    ],
  };
  const metric = widget.metrics[0];
  return (
    <div className="space-y-2">
      {metric && (
        <p className="text-sm text-muted-foreground">
          {metric.id}:{" "}
          <ValueLink
            point={widget.points[metric.id]}
            metric={metric}
            className="text-foreground underline"
          />{" "}
          open more than 180 days.{" "}
          <Link to="/exceptions" className="underline underline-offset-4">
            Open the register
          </Link>
        </p>
      )}
      <ChartFrame
        name={widget.title}
        chart={<EChart label={`${widget.title}: open exceptions by age`} option={option} />}
        table={
          <table className="w-full text-sm">
            <caption className="sr-only">{widget.title}</caption>
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th scope="col" className="px-2 py-1 font-medium">
                  Age since approval
                </th>
                <th scope="col" className="px-2 py-1 font-medium">
                  Open exceptions
                </th>
              </tr>
            </thead>
            <tbody>
              {widget.buckets.map((b) => (
                <tr key={b.label} className="border-t-[0.5px] border-border">
                  <th scope="row" className="px-2 py-1 text-left font-normal">
                    {b.label}
                  </th>
                  <td className="px-2 py-1 tabular">{b.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        }
      />
    </div>
  );
}

export function FindingsBurndownWidget({ widget }: { widget: Widget }) {
  const open = widget.buckets.reduce((sum, b) => sum + b.count, 0);
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">Open findings by severity</p>
      <dl className="grid grid-cols-4 gap-2 text-center">
        {widget.buckets.map((b) => (
          <div key={b.label} className="rounded-lg bg-surface-muted px-2 py-1.5">
            <dt className="text-xs text-muted-foreground">{humanize(b.label)}</dt>
            <dd className="text-lg font-semibold tabular">
              <Link to={`/findings?severity=${b.label}`} className="hover:underline">
                {b.count}
              </Link>
            </dd>
          </div>
        ))}
      </dl>
      <p className="sr-only">{open} open findings in total.</p>
      <TrendWidget widget={widget} />
    </div>
  );
}
