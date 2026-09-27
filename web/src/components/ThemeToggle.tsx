import { Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";

import { applyPreference, readPreference, type ThemePreference } from "@/lib/theme";
import { cn } from "@/lib/utils";

const OPTIONS: { value: ThemePreference; label: string; Icon: typeof Sun }[] = [
  { value: "system", label: "System theme", Icon: Monitor },
  { value: "light", label: "Light theme", Icon: Sun },
  { value: "dark", label: "Dark theme", Icon: Moon },
];

export function ThemeToggle() {
  const [pref, setPref] = useState<ThemePreference>(readPreference);

  return (
    <div role="group" aria-label="Theme" className="flex rounded-lg border border-border p-0.5">
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          aria-label={label}
          aria-pressed={pref === value}
          title={label}
          onClick={() => {
            setPref(value);
            applyPreference(value);
          }}
          className={cn(
            "inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground",
            pref === value && "bg-surface-muted text-foreground",
          )}
        >
          <Icon className="size-4" aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}
