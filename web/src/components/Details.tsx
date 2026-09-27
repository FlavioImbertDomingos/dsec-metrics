import type * as React from "react";

/** A definition list laid out in two columns. */
export function Facts({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm">
      {items.map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-muted-foreground">{term}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Pretty-printed JSON, for definitions and calculation records. */
export function JsonBlock({ value, label }: { value: unknown; label: string }) {
  return (
    <pre
      role="region"
      aria-label={label}
      // A scrollable region must be reachable by keyboard.
      tabIndex={0}
      className="max-h-96 overflow-auto rounded-lg bg-surface-muted p-3 text-xs leading-relaxed"
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** A titled card section. */
export function Section({
  title,
  children,
  actions,
}: {
  title: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  const id = `s-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section
      aria-labelledby={id}
      className="min-w-0 rounded-card border-[0.5px] border-border bg-surface p-5"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id={id} className="text-base font-semibold">
          {title}
        </h2>
        {actions}
      </div>
      {children}
    </section>
  );
}
