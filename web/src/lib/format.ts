/** Number, date and label formatting. Numbers use tabular figures in the UI. */

const number = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
const whole = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });

/** A metric value with its unit, or an em dash when there is no value. */
export function formatValue(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined) return "—";
  switch (unit) {
    case "percent":
      return `${number.format(value)}%`;
    case "days":
      return `${number.format(value)} ${value === 1 ? "day" : "days"}`;
    case "count":
      return Number.isInteger(value) ? whole.format(value) : number.format(value);
    default:
      return number.format(value);
  }
}

/** A signed change such as "+2" or "−1.5 pts". Zero reads "no change". */
export function formatDelta(value: number | null | undefined, unit: string): string | null {
  if (value === null || value === undefined) return null;
  if (value === 0) return "no change";
  const sign = value > 0 ? "+" : "−";
  const size = number.format(Math.abs(value));
  return unit === "percent" ? `${sign}${size} pts` : `${sign}${size}`;
}

/** Whether a change is an improvement, given the metric's direction. */
export function deltaTone(value: number | null | undefined, higherIsBetter: boolean) {
  if (!value) return "neutral" as const;
  return value > 0 === higherIsBetter ? ("better" as const) : ("worse" as const);
}

const dateFormat = new Intl.DateTimeFormat("en", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const monthFormat = new Intl.DateTimeFormat("en", {
  month: "short",
  year: "2-digit",
  timeZone: "UTC",
});

/** "30 Sep 2026" style dates from ISO strings. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date);
}

/** Short month label for chart axes. */
export function formatMonth(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? iso : monthFormat.format(date);
}

/** "business_unit" -> "Business unit". */
export function humanize(name: string): string {
  const text = name.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The first 12 characters of a hash, for display next to the full value. */
export function shortHash(sha256: string): string {
  return sha256.slice(0, 12);
}
