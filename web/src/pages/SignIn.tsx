import { CircleAlert } from "lucide-react";
import { useId, useState } from "react";

import { ApiError, type Meta } from "@/api/client";
import { useSignIn } from "@/auth/session";
import { DevBadge } from "@/components/AppShell";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Card, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Wrong username or password.";
    if (error.status === 429) return "Too many attempts. Wait a few minutes and try again.";
    if (error.status === 404) return "Local sign-in is turned off on this server.";
  }
  return "Sign-in failed. Check that the server is running and try again.";
}

export function SignIn({ meta }: { meta: Meta | undefined }) {
  const signIn = useSignIn();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const errorId = useId();
  const hasError = signIn.isError;

  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex justify-end p-4" data-print="hide">
        <ThemeToggle />
      </div>
      <main id="main" className="flex flex-1 items-start justify-center px-4 pt-[12vh]">
        <Card className="w-full max-w-sm">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold">
              Sign in to {meta?.product_name ?? "dsec-metrics"}
            </h1>
          </div>
          {meta?.mode === "development" && (
            <div className="mt-2 flex flex-col items-start gap-2">
              <DevBadge />
              <CardDescription className="mt-0">
                Local accounts are for development only. Production sign-in uses your identity
                provider.
              </CardDescription>
            </div>
          )}
          <form
            className="mt-6 space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              signIn.mutate({ username: username.trim(), password });
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                name="username"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value);
                }}
                aria-invalid={hasError || undefined}
                aria-describedby={hasError ? errorId : undefined}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                }}
                aria-invalid={hasError || undefined}
                aria-describedby={hasError ? errorId : undefined}
              />
            </div>
            {hasError && (
              <p
                id={errorId}
                role="alert"
                className="flex items-center gap-2 rounded-lg bg-danger-surface px-3 py-2 text-sm text-danger"
              >
                <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
                {errorMessage(signIn.error)}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={signIn.isPending}>
              {signIn.isPending ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </Card>
      </main>
    </div>
  );
}
