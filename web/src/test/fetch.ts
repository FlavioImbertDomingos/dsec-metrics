import { vi } from "vitest";

export type Route = (init: RequestInit | undefined) => { status: number; body?: unknown };

/** Stub fetch with a map of "METHOD /path" to responders. Returns the mock for assertions. */
export function stubFetch(routes: Record<string, Route>) {
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const route = routes[`${method} ${url}`];
    if (!route) return Promise.resolve(new Response("not stubbed", { status: 599 }));
    const { status, body } = route(init);
    const payload = body === undefined || status === 204 ? null : JSON.stringify(body);
    return Promise.resolve(
      new Response(payload, { status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
