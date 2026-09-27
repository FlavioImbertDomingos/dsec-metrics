/** Minimal JSON client for the dsec-metrics API. Same-origin only. */

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let csrfToken: string | null = null;

/** Remember the CSRF token from sign-in or /api/me for later unsafe requests. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE.has(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: init.body === undefined ? null : JSON.stringify(init.body),
  });
  if (!response.ok) {
    let detail = response.statusText || "Request failed";
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      // Body was not JSON; keep the status text.
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface Me {
  username: string;
  display_name: string;
  csrf_token: string;
}

export interface Meta {
  product_name: string;
  version: string;
  mode: "development" | "production";
}
