import { CircleAlert, Inbox } from "lucide-react";
import type * as React from "react";

import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";

/** A grey block that stands in for content while it loads. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-card bg-surface-muted", className)} />;
}

/** Loading placeholder that also tells screen readers what is loading. */
export function Loading({ what, children }: { what: string; children?: React.ReactNode }) {
  return (
    <div aria-busy="true" aria-live="polite">
      <p className="sr-only">Loading {what}…</p>
      {children ?? <Skeleton className="h-40" />}
    </div>
  );
}

/** Says what to do next when there is nothing to show. */
export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border-[0.5px] border-dashed border-border px-6 py-10 text-center">
      <Inbox className="size-6 text-muted-foreground" aria-hidden="true" />
      <p className="font-medium">{title}</p>
      {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

/** A failed request, with a message that fits the status code. */
export function ErrorState({ error }: { error: unknown }) {
  const status = error instanceof ApiError ? error.status : 0;
  const message =
    status === 404
      ? "This item does not exist, or it is outside what you can see."
      : status === 429
        ? "Too many requests. Wait a minute and reload."
        : "Something went wrong loading this. Reload the page to try again.";
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-card border-[0.5px] border-border bg-danger-surface px-4 py-3 text-sm text-danger"
    >
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p>{message}</p>
    </div>
  );
}

/** Page heading with optional lead text and actions. */
export function PageHeader({
  title,
  lead,
  actions,
}: {
  title: React.ReactNode;
  lead?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {lead && <div className="mt-1 text-sm text-muted-foreground">{lead}</div>}
      </div>
      {actions && (
        <div className="flex items-center gap-2" data-print="hide">
          {actions}
        </div>
      )}
    </div>
  );
}
