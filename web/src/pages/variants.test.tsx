import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Widget } from "@/api/types";
import { useChartTheme } from "@/charts/EChart";
import { Routes } from "@/Routes";
import { type Route, stubFetch } from "@/test/fetch";
import {
  CONTROL,
  DASHBOARD,
  DASHBOARDS,
  EXCEPTION,
  EXCEPTIONS,
  FINDINGS,
  HISTORY,
  KCI,
  KRI,
  MEASUREMENT,
  METRIC,
} from "@/test/fixtures";
import { WidgetCard } from "@/widgets/WidgetCard";

const ok = (body: unknown) => () => ({ status: 200, body });

function show(path: string, routes: Record<string, Route>) {
  window.history.replaceState(null, "", path);
  stubFetch(routes);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Routes />
    </QueryClientProvider>,
  );
}

function Theme() {
  const theme = useChartTheme();
  return <p>{theme.dark ? "dark" : "light"}</p>;
}

describe("edge cases", () => {
  it("shows loading placeholders while requests are pending", () => {
    show("/dashboards/risk-committee", {
      "GET /api/dashboards/risk-committee": () => ({ status: 200, body: DASHBOARD }),
    });
    expect(screen.getByText("Loading the dashboard…")).toBeDefined();
  });

  it("chart colours follow the theme class", async () => {
    render(<Theme />);
    expect(screen.getByText("light")).toBeDefined();
    act(() => {
      document.documentElement.classList.add("dark");
    });
    expect(await screen.findByText("dark")).toBeDefined();
  });

  it("dashboard without measurements explains the next step", async () => {
    show("/dashboards/risk-committee", {
      "GET /api/dashboards/risk-committee": ok({ ...DASHBOARD, as_of: null, dimensions: {} }),
    });
    expect(await screen.findByText("Nothing measured yet")).toBeDefined();
  });

  it("overview with nothing red says so", async () => {
    show("/", {
      "GET /api/dashboards": ok(DASHBOARDS),
      "GET /api/metrics": ok([KCI]),
    });
    expect(await screen.findByText("No indicator is red.")).toBeDefined();
  });

  it("metric detail without slices, baseline or target", async () => {
    show("/metrics/KRI-06", {
      "GET /api/metrics/KRI-06": ok({ ...METRIC, baseline: null, target: null, group_by: [] }),
      "GET /api/metrics/KRI-06/measurements": ok({
        ...HISTORY,
        slices: [],
        points: [],
        bands: { green: { min: 1, max: null, above: null, below: 9 }, amber: null, red: null },
      }),
    });
    expect(await screen.findByText("This metric is not broken down.")).toBeDefined();
    expect(screen.getByText("at least 1 and below 9")).toBeDefined();
    expect(screen.getAllByText("Not set").length).toBe(3);
    expect(screen.getByText("all business units, no data")).toBeDefined();
  });

  it("measurement with no batches explains the unknown status", async () => {
    show("/measurements/11", {
      "GET /api/measurements/11": ok({
        ...MEASUREMENT,
        dimensions: { business_unit: "cards" },
        point: { ...MEASUREMENT.point, value: null, status: "unknown" },
        batches: [],
        missing_batches: [],
      }),
    });
    expect(await screen.findByText(/nothing was collected/)).toBeDefined();
    expect(screen.getByText("No value")).toBeDefined();
  });

  it("control without metrics, evidence or open items", async () => {
    show("/controls/DS-SM-02", {
      "GET /api/controls/DS-SM-02": ok({
        ...CONTROL,
        description: "",
        metrics: [],
        evidence: [],
        exceptions: [],
        findings: [],
      }),
    });
    expect(await screen.findByText("No metrics measure this control yet.")).toBeDefined();
    expect(screen.getByText("No evidence sources configured.")).toBeDefined();
    expect(screen.getByText("No exceptions for this control")).toBeDefined();
    expect(screen.getByText("No findings for this control")).toBeDefined();
  });

  it("registers with sparse records and nothing expiring", async () => {
    const sparse = {
      ...EXCEPTION,
      control_id: null,
      risk_rating: null,
      root_cause: null,
      owner: null,
      expires_at: null,
      days_to_expiry: null,
      age_days: null,
      business_unit: null,
    };
    show("/exceptions", {
      "GET /api/exceptions": ok({ ...EXCEPTIONS, skipped: 0, source: null, items: [sparse] }),
    });
    expect(await screen.findByText("Nothing expires in the next 180 days.")).toBeDefined();
    expect(screen.getByText("No expiry")).toBeDefined();
  });

  it("findings page with no matches", async () => {
    show("/findings", { "GET /api/findings": ok({ ...FINDINGS, items: [] }) });
    expect(await screen.findByText("No findings match")).toBeDefined();
  });

  it("widgets cope with missing points, series and cells", () => {
    const first = DASHBOARD.widgets[0];
    if (!first) throw new Error("fixture has no widgets");
    const base: Widget = {
      ...first,
      points: {},
      series: [],
      metrics: [{ ...KRI, target: null }],
    };
    render(
      <>
        <WidgetCard widget={{ ...base, widget: "stat", title: "S" }} query="" />
        <WidgetCard widget={{ ...base, widget: "stat", title: "Empty", metrics: [] }} query="" />
        <WidgetCard widget={{ ...base, widget: "bar", title: "B", cells: [] }} query="" />
        <WidgetCard widget={{ ...base, widget: "table", title: "T" }} query="" />
        <WidgetCard
          widget={{ ...base, widget: "exceptions_aging", title: "E", metrics: [] }}
          query=""
        />
        <WidgetCard
          widget={{
            ...base,
            widget: "heatmap",
            title: "H",
            rows: ["cards"],
            columns: ["KRI-06"],
            cells: [],
          }}
          query=""
        />
      </>,
    );
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—", { selector: "td" }).length).toBeGreaterThan(0);
  });
});
