import type * as React from "react";

import type { MetricSummary, Point } from "@/api/types";
import { deltaTone, formatDate, formatDelta, formatValue } from "@/lib/format";
import { Link } from "@/lib/router";
import { cn } from "@/lib/utils";

/** A value that opens the measurement behind it. Every number on screen uses this. */
export function ValueLink({
  point,
  metric,
  className,
  children,
}: {
  point: Point | null | undefined;
  metric: Pick<MetricSummary, "id" | "unit">;
  className?: string;
  children?: React.ReactNode;
}) {
  const text = children ?? formatValue(point?.value, metric.unit);
  if (!point) return <span className={cn("tabular", className)}>{text}</span>;
  return (
    <Link
      to={`/measurements/${String(point.measurement_id)}`}
      className={cn("tabular underline-offset-4 hover:underline", className)}
      title={`${metric.id} on ${formatDate(point.as_of)}: open the measurement`}
    >
      {text}
    </Link>
  );
}

/** A metric id and name that open the metric's detail page. */
export function MetricLink({
  metric,
  query = "",
  className,
}: {
  metric: Pick<MetricSummary, "id" | "name">;
  query?: string;
  className?: string;
}) {
  return (
    <Link
      to={`/metrics/${metric.id}${query}`}
      className={cn("underline-offset-4 hover:underline", className)}
    >
      <span className="font-medium">{metric.id}</span> {metric.name}
    </Link>
  );
}

/** Change from a reference value, coloured by whether it is an improvement. */
export function Delta({
  value,
  metric,
  label,
}: {
  value: number | null | undefined;
  metric: Pick<MetricSummary, "unit" | "higher_is_better">;
  label: string;
}) {
  const text = formatDelta(value, metric.unit);
  if (text === null) return null;
  const tone = deltaTone(value, metric.higher_is_better);
  return (
    <span
      className={cn(
        "tabular whitespace-nowrap text-xs",
        tone === "better" && "text-status-green",
        tone === "worse" && "text-status-red",
        tone === "neutral" && "text-muted-foreground",
      )}
    >
      {text} <span className="text-muted-foreground">{label}</span>
    </span>
  );
}
