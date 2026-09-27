import { Info } from "lucide-react";
import { useId } from "react";

import type { Widget } from "@/api/types";
import { cn } from "@/lib/utils";
import {
  BarWidget,
  ExceptionsAgingWidget,
  FindingsBurndownWidget,
  HeatmapWidget,
  TrendWidget,
} from "@/widgets/ChartWidgets";
import { MetricTableWidget, StatWidget } from "@/widgets/MetricWidgets";

// Tailwind needs literal class names, so the twelve spans are listed.
const SPAN: Record<number, string> = {
  1: "lg:col-span-1",
  2: "lg:col-span-2",
  3: "lg:col-span-3",
  4: "lg:col-span-4",
  5: "lg:col-span-5",
  6: "lg:col-span-6",
  7: "lg:col-span-7",
  8: "lg:col-span-8",
  9: "lg:col-span-9",
  10: "lg:col-span-10",
  11: "lg:col-span-11",
  12: "lg:col-span-12",
};

function Body({ widget, query }: { widget: Widget; query: string }) {
  switch (widget.widget) {
    case "stat":
      return <StatWidget widget={widget} query={query} />;
    case "table":
    case "rag_list":
      return <MetricTableWidget widget={widget} query={query} />;
    case "trend":
      return <TrendWidget widget={widget} />;
    case "bar":
      return <BarWidget widget={widget} />;
    case "heatmap":
      return <HeatmapWidget widget={widget} />;
    case "exceptions_aging":
      return <ExceptionsAgingWidget widget={widget} />;
    case "findings_burndown":
      return <FindingsBurndownWidget widget={widget} />;
  }
}

/** A dashboard card: title, any note about filters, and the widget body. */
export function WidgetCard({ widget, query }: { widget: Widget; query: string }) {
  const isStat = widget.widget === "stat";
  const headingId = useId();
  return (
    <section
      data-widget={widget.widget}
      aria-label={isStat ? widget.title : undefined}
      aria-labelledby={isStat ? undefined : headingId}
      className={cn(
        "col-span-12 min-w-0 rounded-card border-[0.5px] border-border bg-surface p-4 md:col-span-6",
        SPAN[widget.width],
        widget.width <= 3 && "md:col-span-3",
      )}
    >
      {!isStat && (
        <h2 id={headingId} className="mb-2 text-sm font-semibold">
          {widget.title}
        </h2>
      )}
      {widget.note && (
        <p className="mb-2 flex items-start gap-1.5 text-xs text-muted-foreground">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          {widget.note}
        </p>
      )}
      <Body widget={widget} query={query} />
    </section>
  );
}
