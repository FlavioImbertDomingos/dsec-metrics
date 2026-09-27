/** Dimension filters live in the URL so every view can be shared as a link. */
import { navigate, useLocation, withQuery } from "@/lib/router";

export const DIMENSIONS = ["business_unit", "application", "environment", "region"] as const;
export type Dimension = (typeof DIMENSIONS)[number];
export type Filters = Partial<Record<Dimension, string>>;

export function readFilters(search: URLSearchParams): Filters {
  const filters: Filters = {};
  for (const dim of DIMENSIONS) {
    const value = search.get(dim);
    if (value) filters[dim] = value;
  }
  return filters;
}

/** The current filters and a setter that updates the URL in place. */
export function useFilters(): [Filters, (next: Filters) => void] {
  const { path, search } = useLocation();
  const filters = readFilters(search);
  const set = (next: Filters) => {
    const params: Record<string, string | undefined> = {};
    for (const [key, value] of search.entries()) {
      if (!(DIMENSIONS as readonly string[]).includes(key)) params[key] = value;
    }
    navigate(withQuery(path, { ...params, ...next }), { replace: true });
  };
  return [filters, set];
}
