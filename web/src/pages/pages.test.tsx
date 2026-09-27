import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { navigate } from "@/lib/router";
import { Routes } from "@/Routes";
import { type Route, stubFetch } from "@/test/fetch";
import {
  BATCH,
  CONTROL,
  CONTROLS,
  DASHBOARD,
  DASHBOARDS,
  EXCEPTIONS,
  FINDINGS,
  HISTORY,
  KCI,
  KRI,
  MEASUREMENT,
  METRIC,
} from "@/test/fixtures";

const ok = (body: unknown) => () => ({ status: 200, body });
const SHA = "a".repeat(64);

const ROUTES: Record<string, Route> = {
  "GET /api/dashboards": ok(DASHBOARDS),
  "GET /api/metrics": ok([KRI, KCI]),
  "GET /api/dashboards/risk-committee": ok(DASHBOARD),
  "GET /api/dashboards/risk-committee?business_unit=cards": ok({
    ...DASHBOARD,
    filters: { business_unit: "cards" },
  }),
  "GET /api/metrics/KRI-06": ok(METRIC),
  "GET /api/metrics/KRI-06/measurements": ok(HISTORY),
  "GET /api/metrics/KRI-06/measurements?region=emea": ok({
    ...HISTORY,
    ignored_filters: ["region"],
  }),
  "GET /api/measurements/11": ok(MEASUREMENT),
  [`GET /api/batches/${SHA}?offset=0&limit=50`]: ok(BATCH),
  [`GET /api/batches/${SHA}?offset=50&limit=50`]: ok({ ...BATCH, offset: 50 }),
  "GET /api/controls": ok(CONTROLS),
  "GET /api/controls/DS-SM-02": ok(CONTROL),
  "GET /api/exceptions": ok(EXCEPTIONS),
  "GET /api/exceptions?business_unit=cards": ok({ ...EXCEPTIONS, items: [] }),
  "GET /api/findings": ok(FINDINGS),
  "GET /api/findings?severity=high": ok(FINDINGS),
  "GET /api/controls/DS-XX-99": () => ({ status: 404, body: { detail: "Control not found" } }),
  "GET /api/metrics/KRI-99": () => ({ status: 429, body: { detail: "x" } }),
  "GET /api/measurements/99": () => ({ status: 500, body: { detail: "x" } }),
};

function show(path: string, routes: Record<string, Route> = ROUTES) {
  window.history.replaceState(null, "", path);
  stubFetch(routes);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Routes />
    </QueryClientProvider>,
  );
}

describe("screens", () => {
  it("overview shows audiences and what is red", async () => {
    show("/");
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeDefined();
    const audiences = screen.getByRole("navigation", { name: "Audiences" });
    expect(within(audiences).getByRole("link", { name: /Risk committee/ })).toBeDefined();
    expect(screen.getByText("Rotate overdue secrets.", { exact: false })).toBeDefined();
  });

  it("overview says how to load data when nothing is measured", async () => {
    show("/", { ...ROUTES, "GET /api/metrics": ok([{ ...KRI, latest: null }]) });
    expect(await screen.findByText("No measurements yet")).toBeDefined();
  });

  it("dashboard renders every widget type with links to measurements", async () => {
    const user = userEvent.setup();
    show("/dashboards/risk-committee");
    expect(await screen.findByRole("heading", { name: "Risk committee" })).toBeDefined();
    for (const kind of [
      "rag_list",
      "table",
      "trend",
      "bar",
      "heatmap",
      "exceptions_aging",
      "findings_burndown",
    ]) {
      expect(screen.getByRole("region", { name: `A ${kind} widget` })).toBeDefined();
    }
    expect(screen.getByText(/not broken down by region/)).toBeDefined();
    const links = screen.getAllByRole("link", { name: "7" });
    expect(links[0]?.getAttribute("href")).toBe("/measurements/11");
    expect(screen.getByText("None needed")).toBeDefined();
    expect(screen.getAllByText("Rotate overdue secrets.").length).toBeGreaterThan(0);

    const toggle = screen.getByRole("button", { name: "View A trend widget as table" });
    await user.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");

    await user.selectOptions(screen.getByLabelText("Business unit"), "cards");
    expect(window.location.search).toBe("?business_unit=cards");
    await user.click(await screen.findByRole("button", { name: "Clear filters" }));
    expect(window.location.search).toBe("");
  });

  it("sorts tables from their headers", async () => {
    const user = userEvent.setup();
    show("/metrics");
    const table = await screen.findByRole("table", { name: "Metric catalog" });
    const header = within(table).getByRole("columnheader", { name: /Value/ });
    expect(header.getAttribute("aria-sort")).toBeNull();
    await user.click(within(header).getByRole("button"));
    const first = header.getAttribute("aria-sort");
    expect(["ascending", "descending"]).toContain(first);
    await user.click(within(header).getByRole("button"));
    expect(header.getAttribute("aria-sort")).not.toBe(first);
  });

  it("metric detail shows bands, breakdown, definition and versions", async () => {
    show("/metrics/KRI-06");
    expect(await screen.findByRole("heading", { name: /KRI-06 Secrets older/ })).toBeDefined();
    expect(screen.getByText("above 6")).toBeDefined();
    expect(screen.getByRole("rowheader", { name: "cards" })).toBeDefined();
    expect(screen.getByText("Version 1")).toBeDefined();
    expect(screen.getByRole("link", { name: "DS-SM-02" })).toBeDefined();
    expect(screen.getByRole("region", { name: "KRI-06 definition" })).toBeDefined();
  });

  it("metric detail says when a filter does not apply", async () => {
    show("/metrics/KRI-06?region=emea");
    expect(await screen.findByText(/not broken down by region/)).toBeDefined();
  });

  it("measurement links to its batches and notes missing ones", async () => {
    show("/measurements/11");
    expect(await screen.findByRole("heading", { name: "Measurement 11" })).toBeDefined();
    const batch = screen.getByRole("link", { name: "sample / secrets_inventory" });
    expect(batch.getAttribute("href")).toBe(`/batches/${SHA}`);
    expect(screen.getByText(/no longer stored/)).toBeDefined();
  });

  it("batch shows provenance, redaction and pages of records", async () => {
    const user = userEvent.setup();
    show(`/batches/${SHA}`);
    expect(
      await screen.findByRole("heading", { name: "sample / secrets_inventory" }),
    ).toBeDefined();
    expect(screen.getByText("card_holder_name (1)")).toBeDefined();
    expect(screen.getByText("kv/cards/app/secret-000")).toBeDefined();
    expect(screen.getByText('{"a":1}')).toBeDefined();
    await user.click(screen.getByRole("link", { name: "Next" }));
    expect(window.location.search).toBe("?offset=50");
  });

  it("controls list and detail", async () => {
    show("/controls");
    expect(await screen.findByRole("link", { name: /DS-SM-02 Secrets are rotated/ })).toBeDefined();
  });

  it("control detail shows requirements, evidence and registers", async () => {
    show("/controls/DS-SM-02");
    expect(await screen.findByRole("heading", { name: /DS-SM-02/ })).toBeDefined();
    expect(screen.getByText("Not collected yet")).toBeDefined();
    expect(screen.getByRole("table", { name: "Exceptions for DS-SM-02" })).toBeDefined();
    expect(screen.getByRole("table", { name: "Findings for DS-SM-02" })).toBeDefined();
  });

  it("exceptions page shows tallies, root causes, calendar and register", async () => {
    const user = userEvent.setup();
    show("/exceptions");
    expect(await screen.findByRole("heading", { name: "Exceptions" })).toBeDefined();
    expect(screen.getByText("Legacy platform", { selector: "span" })).toBeDefined();
    expect(screen.getByText("October 2026")).toBeDefined();
    expect(screen.getByText(/1 records were skipped/)).toBeDefined();
    expect(screen.getByText("Expired 5 days ago")).toBeDefined();
    await user.selectOptions(screen.getByLabelText("Business unit"), "cards");
    expect(await screen.findByText("No exceptions match")).toBeDefined();
  });

  it("findings page filters by severity from the URL", async () => {
    show("/findings?severity=high");
    expect(await screen.findByRole("heading", { name: "High findings" })).toBeDefined();
    expect(screen.getByRole("table", { name: "Findings register" })).toBeDefined();
  });

  it.each([
    ["/controls/DS-XX-99", "This item does not exist"],
    ["/metrics/KRI-99", "Too many requests"],
    ["/measurements/99", "Something went wrong"],
  ])("explains errors on %s", async (path, text) => {
    show(path);
    expect((await screen.findByRole("alert")).textContent).toContain(text);
  });

  it("unknown paths get a not-found page", () => {
    show("/nowhere");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeDefined();
    navigate("/");
  });
});
