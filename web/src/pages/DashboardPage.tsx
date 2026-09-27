import { Printer } from "lucide-react";

import { useDashboard } from "@/api/hooks";
import { FilterBar } from "@/components/FilterBar";
import { EmptyState, ErrorState, Loading, PageHeader, Skeleton } from "@/components/States";
import { Button } from "@/components/ui/button";
import { useFilters } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { withQuery } from "@/lib/router";
import { WidgetCard } from "@/widgets/WidgetCard";

export function DashboardPage({ id }: { id: string }) {
  const [filters, setFilters] = useFilters();
  const dashboard = useDashboard(id, filters);

  if (dashboard.isError) return <ErrorState error={dashboard.error} />;
  const data = dashboard.data;
  if (!data) {
    return (
      <Loading what="the dashboard">
        <Skeleton className="mb-6 h-8 w-64" />
        <div className="grid grid-cols-12 gap-4">
          {[12, 6, 6, 6, 6].map((w, i) => (
            <Skeleton key={i} className={w === 12 ? "col-span-12 h-64" : "col-span-6 h-56"} />
          ))}
        </div>
      </Loading>
    );
  }
  const query = withQuery("", filters);
  return (
    <div aria-busy={dashboard.isFetching}>
      <PageHeader
        title={data.title}
        lead={
          data.as_of
            ? `As of ${formatDate(data.as_of)}. Refreshed ${data.refresh}. Select any number to see how it was measured.`
            : "No measurements yet."
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              window.print();
            }}
          >
            <Printer aria-hidden="true" />
            Print
          </Button>
        }
      />
      <FilterBar options={data.dimensions} filters={filters} onChange={setFilters} />
      {data.as_of ? (
        <div className="grid grid-cols-12 gap-4">
          {data.widgets.map((w, i) => (
            <WidgetCard key={`${w.widget}-${String(i)}`} widget={w} query={query} />
          ))}
        </div>
      ) : (
        <EmptyState title="Nothing measured yet">
          Connect a collector, or load the sample data with{" "}
          <code>docker compose exec api dsec-metrics demo</code>.
        </EmptyState>
      )}
    </div>
  );
}
