import { ChartLine, Table } from "lucide-react";
import type * as React from "react";
import { useId, useState } from "react";

import { cn } from "@/lib/utils";

interface ChartFrameProps {
  chart: React.ReactNode;
  table: React.ReactNode;
  /** Name of what the chart shows, used for the toggle's accessible name. */
  name: string;
}

/** Holds a chart and its table equivalent, with a "View as table" toggle. */
export function ChartFrame({ chart, table, name }: ChartFrameProps) {
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  return (
    <div>
      <div className="flex justify-end" data-print="hide">
        <button
          type="button"
          aria-pressed={asTable}
          aria-controls={id}
          aria-label={`View ${name} as table`}
          onClick={() => {
            setAsTable((v) => !v);
          }}
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-surface-muted hover:text-foreground",
            asTable && "bg-surface-muted text-foreground",
          )}
        >
          {asTable ? (
            <ChartLine className="size-3.5" aria-hidden="true" />
          ) : (
            <Table className="size-3.5" aria-hidden="true" />
          )}
          {asTable ? "View as chart" : "View as table"}
        </button>
      </div>
      <div id={id}>
        {/* The table always prints; the chart canvas does not print reliably. */}
        <div className={cn(asTable && "hidden")} data-print="hide">
          {chart}
        </div>
        <div className={cn(!asTable && "hidden print:block")}>{table}</div>
      </div>
    </div>
  );
}
