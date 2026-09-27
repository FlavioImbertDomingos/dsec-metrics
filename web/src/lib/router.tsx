/**
 * A small client-side router over the History API. The app has a handful of screens,
 * so a routing library would add more than it saves (see docs/plans/m2.md).
 */
import type * as React from "react";
import { useSyncExternalStore } from "react";

const EVENT = "dsec:navigate";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

function snapshot(): string {
  return window.location.pathname + window.location.search;
}

export interface Location {
  path: string;
  search: URLSearchParams;
}

/** The current path and query string. Re-renders on navigation. */
export function useLocation(): Location {
  const href = useSyncExternalStore(subscribe, snapshot, snapshot);
  const url = new URL(href, "https://app.invalid");
  return { path: url.pathname, search: url.searchParams };
}

/** Go to a same-origin path, adding a history entry unless ``replace`` is set. */
export function navigate(to: string, { replace = false }: { replace?: boolean } = {}): void {
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event(EVENT));
  if (!replace) window.scrollTo({ top: 0 });
}

/**
 * Match ``/metrics/:id`` style patterns. Returns decoded parameters, or null.
 * Parameters never contain a slash.
 */
export function match(pattern: string, path: string): Record<string, string> | null {
  const want = pattern.split("/").filter(Boolean);
  const got = path.split("/").filter(Boolean);
  if (want.length !== got.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < want.length; i++) {
    const w = want[i] ?? "";
    const g = got[i] ?? "";
    if (w.startsWith(":")) {
      try {
        params[w.slice(1)] = decodeURIComponent(g);
      } catch {
        return null;
      }
    } else if (w !== g) {
      return null;
    }
  }
  return params;
}

type LinkProps = Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & { to: string };

/** An ordinary link that navigates in place for plain left clicks. */
export function Link({ to, onClick, children, ...props }: LinkProps) {
  return (
    <a
      href={to}
      onClick={(event) => {
        onClick?.(event);
        const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
        if (event.defaultPrevented || event.button !== 0 || modified) return;
        event.preventDefault();
        navigate(to);
      }}
      {...props}
    >
      {children}
    </a>
  );
}

/** Build a path with a query string, dropping empty values. */
export function withQuery(path: string, params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const text = search.toString();
  return text ? `${path}?${text}` : path;
}
