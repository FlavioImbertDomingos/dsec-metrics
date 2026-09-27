import { describe, expect, it, vi } from "vitest";

import { stubFetch } from "@/test/fetch";

import { ApiError, api, setCsrfToken } from "./client";

describe("api", () => {
  it("returns parsed JSON", async () => {
    stubFetch({ "GET /api/meta": () => ({ status: 200, body: { mode: "development" } }) });
    await expect(api("/api/meta")).resolves.toEqual({ mode: "development" });
  });

  it("raises ApiError with the server detail", async () => {
    stubFetch({ "GET /api/me": () => ({ status: 401, body: { detail: "Not signed in" } }) });
    const error = await api("/api/me").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).message).toBe("Not signed in");
  });

  it("keeps the status text when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(new Response("<html>", { status: 502, statusText: "Bad Gateway" })),
      ),
    );
    await expect(api("/api/me")).rejects.toThrow("Bad Gateway");
  });

  it("sends the CSRF token only on unsafe methods", async () => {
    const mock = stubFetch({
      "POST /api/auth/logout": () => ({ status: 204 }),
      "GET /api/me": () => ({ status: 200, body: {} }),
    });
    setCsrfToken("token-123");
    await expect(api("/api/auth/logout", { method: "POST" })).resolves.toBeUndefined();
    await api("/api/me");
    const postHeaders = mock.mock.calls[0]?.[1]?.headers as Record<string, string>;
    const getHeaders = mock.mock.calls[1]?.[1]?.headers as Record<string, string>;
    expect(postHeaders["X-CSRF-Token"]).toBe("token-123");
    expect(getHeaders["X-CSRF-Token"]).toBeUndefined();
    setCsrfToken(null);
  });

  it("serialises a JSON body", async () => {
    const mock = stubFetch({ "POST /api/x": () => ({ status: 200, body: { ok: true } }) });
    await api("/api/x", { method: "POST", body: { a: 1 } });
    const init = mock.mock.calls[0]?.[1];
    expect(init?.body).toBe('{"a":1}');
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(init?.credentials).toBe("same-origin");
  });
});
