import { useMe, useMeta } from "@/auth/session";
import { AppShell } from "@/components/AppShell";
import { Home } from "@/pages/Home";
import { SignIn } from "@/pages/SignIn";

export function App() {
  const me = useMe();
  const meta = useMeta();

  if (me.isPending) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8" aria-busy="true" aria-live="polite">
        <p className="sr-only">Loading your session…</p>
        <div className="h-8 w-64 animate-pulse rounded-lg bg-surface-muted" />
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-36 animate-pulse rounded-card bg-surface-muted" />
          ))}
        </div>
      </div>
    );
  }

  if (me.isError) {
    return (
      <main id="main" className="mx-auto max-w-xl px-6 py-16">
        <h1 className="text-lg font-semibold">The API is not reachable</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Check that the api service is running (<code>docker compose ps</code>), then reload this
          page.
        </p>
      </main>
    );
  }

  if (!me.data) return <SignIn meta={meta.data} />;

  return (
    <AppShell me={me.data} meta={meta.data}>
      <Home me={me.data} />
    </AppShell>
  );
}
