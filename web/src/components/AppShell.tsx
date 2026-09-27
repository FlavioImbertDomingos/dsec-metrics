import { LogOut } from "lucide-react";
import type * as React from "react";

import type { Me, Meta } from "@/api/client";
import { useSignOut } from "@/auth/session";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";

interface AppShellProps {
  me: Me;
  meta: Meta | undefined;
  children: React.ReactNode;
}

export function AppShell({ me, meta, children }: AppShellProps) {
  const signOut = useSignOut();

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to main content
      </a>
      <header className="border-b-[0.5px] border-border bg-surface">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-6">
          <span className="font-semibold">{meta?.product_name ?? "dsec-metrics"}</span>
          {meta?.mode === "development" && <DevBadge />}
          <div className="ml-auto flex items-center gap-3" data-print="hide">
            <ThemeToggle />
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {me.display_name}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                signOut.mutate();
              }}
              disabled={signOut.isPending}
            >
              <LogOut aria-hidden="true" />
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-6 py-8">
        {children}
      </main>
    </div>
  );
}

export function DevBadge() {
  return (
    <span className="rounded-md bg-warning-surface px-2 py-0.5 text-xs font-medium text-warning-foreground">
      Development mode
    </span>
  );
}
