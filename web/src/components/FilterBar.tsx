import { FunnelX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DIMENSIONS, type Dimension, type Filters } from "@/lib/filters";
import { humanize } from "@/lib/format";

interface FilterBarProps {
  /** Values offered for each dimension; dimensions without values are not shown. */
  options: Partial<Record<string, string[]>>;
  filters: Filters;
  onChange: (next: Filters) => void;
}

/** One select per dimension. Changes update the URL so the view can be shared. */
export function FilterBar({ options, filters, onChange }: FilterBarProps) {
  const shown = DIMENSIONS.filter((d) => (options[d]?.length ?? 0) > 0 || filters[d]);
  if (shown.length === 0) return null;
  const active = Object.keys(filters).length > 0;
  return (
    <form
      aria-label="Filters"
      className="mb-6 flex flex-wrap items-end gap-3"
      data-print="hide"
      onSubmit={(e) => {
        e.preventDefault();
      }}
    >
      {shown.map((dim: Dimension) => {
        const id = `filter-${dim}`;
        const values = options[dim] ?? [];
        const current = filters[dim] ?? "";
        return (
          <div key={dim} className="flex flex-col gap-1">
            <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
              {humanize(dim)}
            </label>
            <select
              id={id}
              value={current}
              onChange={(e) => {
                const rest = Object.fromEntries(
                  Object.entries(filters).filter(([key]) => key !== dim),
                ) as Filters;
                onChange(e.target.value ? { ...rest, [dim]: e.target.value } : rest);
              }}
              className="h-9 min-w-40 rounded-lg border border-border bg-surface px-2 text-sm"
            >
              <option value="">All</option>
              {[...new Set([...values, ...(current ? [current] : [])])].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
        );
      })}
      {active && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            onChange({});
          }}
        >
          <FunnelX aria-hidden="true" />
          Clear filters
        </Button>
      )}
    </form>
  );
}
