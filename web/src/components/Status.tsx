import { CircleCheck, CircleQuestionMark, OctagonX, TriangleAlert } from "lucide-react";

import type { Status } from "@/api/types";
import { cn } from "@/lib/utils";

export const STATUS_LABEL: Record<Status, string> = {
  green: "Green",
  amber: "Amber",
  red: "Red",
  unknown: "Unknown",
};

const ICON = {
  green: CircleCheck,
  amber: TriangleAlert,
  red: OctagonX,
  unknown: CircleQuestionMark,
};

const TONE: Record<Status, string> = {
  green: "text-status-green bg-status-green-surface",
  amber: "text-status-amber bg-status-amber-surface",
  red: "text-status-red bg-status-red-surface",
  unknown: "text-status-unknown bg-status-unknown-surface",
};

/** Status as icon, label and colour together; colour is never the only signal. */
export function StatusBadge({ status, className }: { status: Status; className?: string }) {
  const Icon = ICON[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium",
        TONE[status],
        className,
      )}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  );
}
