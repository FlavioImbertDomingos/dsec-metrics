import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Route, stubFetch } from "@/test/fetch";

import { App } from "./App";

const META = { product_name: "dsec-metrics", version: "0.0.1a1", mode: "development" };
const ME = {
  username: "dev-admin",
  display_name: "Development admin",
  csrf_token: "csrf",
  roles: ["admin"],
};

function renderApp(routes: Record<string, Route>) {
  const mock = stubFetch({ "GET /api/meta": () => ({ status: 200, body: META }), ...routes });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  return mock;
}

describe("App", () => {
  it("shows sign-in when there is no session, then the overview", async () => {
    const user = userEvent.setup();
    renderApp({
      "GET /api/me": () => ({ status: 401, body: { detail: "Not signed in" } }),
      "POST /api/auth/login": () => ({ status: 200, body: ME }),
      "GET /api/dashboards": () => ({ status: 200, body: [] }),
      "GET /api/metrics": () => ({ status: 200, body: [] }),
    });
    expect(await screen.findByRole("heading", { name: "Sign in to dsec-metrics" })).toBeDefined();
    expect(screen.getAllByText("Development mode").length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText("Username"), "dev-admin");
    await user.type(screen.getByLabelText("Password"), "a long password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeDefined();
    expect(screen.getByText("Development admin")).toBeDefined();
    expect(screen.getByRole("link", { name: "Overview" }).getAttribute("aria-current")).toBe(
      "page",
    );
  });

  it.each([
    [401, "Wrong username or password."],
    [429, "Too many attempts. Wait a few minutes and try again."],
    [404, "Local sign-in is turned off on this server."],
    [500, "Sign-in failed. Check that the server is running and try again."],
  ])("explains a %i sign-in failure", async (status, message) => {
    const user = userEvent.setup();
    renderApp({
      "GET /api/me": () => ({ status: 401 }),
      "POST /api/auth/login": () => ({ status, body: { detail: "x" } }),
    });
    await user.type(await screen.findByLabelText("Username"), "dev-admin");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain(message);
    expect(screen.getByLabelText("Username").getAttribute("aria-invalid")).toBe("true");
  });

  it("signs out", async () => {
    const user = userEvent.setup();
    renderApp({
      "GET /api/me": () => ({ status: 200, body: ME }),
      "POST /api/auth/logout": () => ({ status: 204 }),
      "GET /api/dashboards": () => ({ status: 200, body: [] }),
      "GET /api/metrics": () => ({ status: 200, body: [] }),
    });
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in to dsec-metrics" })).toBeDefined();
  });

  it("says so when the API is down", async () => {
    renderApp({ "GET /api/me": () => ({ status: 502 }) });
    expect(await screen.findByRole("heading", { name: "The API is not reachable" })).toBeDefined();
  });
});
