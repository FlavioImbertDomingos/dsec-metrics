import type * as React from "react";

import { cn } from "@/lib/utils";

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  // eslint-disable-next-line jsx-a11y/label-has-associated-control -- callers pass htmlFor
  return <label className={cn("text-sm font-medium", className)} {...props} />;
}
