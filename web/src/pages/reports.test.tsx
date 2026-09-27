import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { AuditEvent, AuditRoom, ReportPackage } from "@/api/types";
import { meKey } from "@/auth/session";
import { AppShell } from "@/components/AppShell";
import { Routes } from "@/Routes";
import { type Route, stubFetch } from "@/test/fetch";

const ok = (body: unknown) => () => ({ status: 200, body });

const PKG: ReportPackage = {
  id: "11111111-2222-3333-4444-555555555555",
  report_type: "framework",
  title: "PCI DSS 4.0.1: 3",
  scope: { framework: "pci-dss-4.0.1" },
  period_start: "2026-07-01",
  period_end: "2026-09-30",
  frameworks: ["pci-dss-4.0.1"],
  manifest_sha256: "d".repeat(64),
  key_fingerprint: "e".repeat(64),
  pdf_rendered: true,
  generated_by: "author",
  generated_at: "2026-09-30T10:00:00Z",
  size: 90_000,
};

const EVENT: AuditEvent = {
  seq: 7,
  occurred_at: "2026-09-30T11:00:00Z",
  actor: "qsa",
  action: "report.download",
  target: `report:${PKG.id}`,
  details: { via: "link:abc" },
  prev_hash: "0".repeat(64),
  hash: "f".repeat(64),
};

const KEY = {
  algorithm: "Ed25519",
  fingerprint: "e".repeat(64),
  pem: "-----BEGIN PUBLIC KEY-----",
};

function show(path: string, roles: string[], routes: Record<string, Route>) {
  window.history.replaceState(null, "", path);
  stubFetch(routes);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const me = { username: "u", display_name: "U", csrf_token: "c", roles };
  client.setQueryData(meKey, me);
  render(
    <QueryClientProvider client={client}>
      <AppShell me={me} meta={undefined}>
        <Routes staff={roles.some((r) => r !== "auditor")} />
      </AppShell>
    </QueryClientProvider>,
  );
}

describe("reports", () => {
  it("authors build a package, download it and make an auditor link", async () => {
    const user = userEvent.setup();
    let posted: unknown = null;
    show("/reports", ["reviewer"], {
      "GET /api/reports": ok([PKG]),
      "GET /api/reports/public-key": ok(KEY),
      "POST /api/reports": (init) => {
        posted = JSON.parse(init?.body as string);
        return { status: 201, body: PKG };
      },
      [`POST /api/reports/${PKG.id}/links`]: () => ({
        status: 201,
        body: { url: "/api/links/tok", expires_at: "2026-10-07T00:00:00Z", username: "qsa" },
      }),
    });
    expect(await screen.findByRole("heading", { name: "Reports" })).toBeDefined();
    await user.selectOptions(screen.getByLabelText("Report type"), "framework");
    await user.clear(screen.getByLabelText("Requirements"));
    await user.type(screen.getByLabelText("Requirements"), "3, 7 ,");
    await user.type(screen.getByLabelText("Prepared for"), "Example QSA");
    await user.click(screen.getByRole("button", { name: "Build and sign" }));
    expect(await screen.findByText(/Built PCI DSS 4.0.1: 3/)).toBeDefined();
    expect(posted).toEqual({
      report_type: "framework",
      period_start: "2026-07-01",
      period_end: "2026-09-30",
      prepared_for: "Example QSA",
      framework: "pci-dss-4.0.1",
      requirements: ["3", "7"],
    });
    const table = screen.getByRole("table", { name: "Report packages" });
    const download = within(table).getByRole("link", { name: "Download" });
    expect(download.getAttribute("href")).toBe(`/api/reports/${PKG.id}/download`);
    await user.click(within(table).getByRole("button", { name: "Auditor link" }));
    await user.type(screen.getByLabelText("Auditor username"), "qsa");
    await user.click(screen.getByRole("button", { name: "Create link" }));
    expect(await screen.findByText(/it is not shown again/)).toBeDefined();
    expect(screen.getByText(/--fingerprint e{64}/)).toBeDefined();
    expect(screen.getByRole("link", { name: "Reports" }).getAttribute("aria-current")).toBe("page");
    expect(screen.queryByRole("link", { name: "Audit log" })).toBeNull();
  });

  it.each([
    ["control", "Control", "DS-SM-02"],
    ["reproducibility", "Metric", "KRI-06"],
  ])("sends the %s scope", async (type, label, value) => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> = {};
    show("/reports", ["admin"], {
      "GET /api/reports": ok([]),
      "GET /api/reports/public-key": () => ({ status: 503, body: { detail: "x" } }),
      "POST /api/reports": (init) => {
        posted = JSON.parse(init?.body as string) as Record<string, unknown>;
        return { status: 503, body: { detail: "Report signing is not set up" } };
      },
    });
    await user.selectOptions(await screen.findByLabelText("Report type"), type);
    expect(screen.getByLabelText<HTMLInputElement>(label).value).toBe(value);
    await user.click(screen.getByRole("button", { name: "Build and sign" }));
    expect((await screen.findByRole("alert")).textContent).toContain("make signing-key");
    expect(Object.values(posted)).toContain(value);
    expect(screen.getByText("No packages yet")).toBeDefined();
    expect(screen.getByRole("link", { name: "Audit log" })).toBeDefined();
  });

  it("viewers see packages but no build form", async () => {
    show("/reports", ["viewer"], {
      "GET /api/reports": ok([]),
      "GET /api/reports/public-key": ok(KEY),
    });
    expect(await screen.findByText("Ask a reviewer to build one.")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Build and sign" })).toBeNull();
  });

  it("explains link errors", async () => {
    const user = userEvent.setup();
    show("/reports", ["reviewer"], {
      "GET /api/reports": ok([PKG]),
      "GET /api/reports/public-key": ok(KEY),
      [`POST /api/reports/${PKG.id}/links`]: () => ({
        status: 422,
        body: { detail: "That user is not an auditor with a current grant covering this report" },
      }),
    });
    await user.click(await screen.findByRole("button", { name: "Auditor link" }));
    await user.type(screen.getByLabelText("Auditor username"), "someone");
    await user.click(screen.getByRole("button", { name: "Create link" }));
    expect((await screen.findByRole("alert")).textContent).toContain("not an auditor");
  });
});

describe("audit room", () => {
  const ROOM: AuditRoom = {
    auditor: true,
    grants: [
      {
        id: "g",
        username: "qsa",
        frameworks: ["pci-dss-4.0.1"],
        period_start: "2026-07-01",
        period_end: "2026-12-31",
        expires_at: "2026-10-30T00:00:00Z",
      },
    ],
    packages: [PKG],
    access_log: [EVENT],
  };

  it("auditors land in the audit room and see only it", async () => {
    show("/dashboards/risk-committee", ["auditor"], {
      "GET /api/audit-room": ok(ROOM),
      "GET /api/reports/public-key": ok(KEY),
    });
    expect(await screen.findByRole("heading", { name: "Audit room" })).toBeDefined();
    expect(screen.getByText(/pci-dss-4.0.1 for Jul 1, 2026/)).toBeDefined();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Audit room"]);
    expect(screen.getByRole("table", { name: "Access log" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Auditor link" })).toBeNull();
  });

  it("staff see every grant; an empty room says so", async () => {
    show("/audit-room", ["admin"], {
      "GET /api/audit-room": ok({ auditor: false, grants: [], packages: [], access_log: [] }),
      "GET /api/reports/public-key": ok(KEY),
    });
    expect(await screen.findByText("No auditor grants.")).toBeDefined();
    expect(screen.getByText("No downloads yet.")).toBeDefined();
    expect(screen.getByText("No packages to show")).toBeDefined();
  });

  it("an auditor without a grant is told who to ask", async () => {
    show("/audit-room", ["auditor"], {
      "GET /api/audit-room": ok({ auditor: true, grants: [], packages: [], access_log: [] }),
      "GET /api/reports/public-key": ok(KEY),
    });
    expect(await screen.findByText(/Ask the compliance team/)).toBeDefined();
  });
});

describe("audit log", () => {
  it("pages, filters and verifies the chain", async () => {
    const user = userEvent.setup();
    let verifyOk = true;
    show("/audit-log", ["admin"], {
      "GET /api/audit/events?limit=50": ok([EVENT, { ...EVENT, seq: 6, hash: "a".repeat(64) }]),
      "GET /api/audit/events?before=6&limit=50": ok([{ ...EVENT, seq: 5 }]),
      "GET /api/audit/events?action=auth.login&limit=50": ok([]),
      "GET /api/audit/verify": () =>
        verifyOk
          ? {
              status: 200,
              body: { ok: true, checked: 7, broken_at: null, reason: null, head: "f".repeat(64) },
            }
          : {
              status: 200,
              body: {
                ok: false,
                checked: 3,
                broken_at: 4,
                reason: "contents do not match",
                head: "",
              },
            },
    });
    expect(await screen.findByRole("heading", { name: "Audit log" })).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Verify chain" }));
    expect(await screen.findByText(/Chain intact: 7 entries/)).toBeDefined();
    verifyOk = false;
    await user.click(screen.getByRole("button", { name: "Verify chain" }));
    expect((await screen.findByRole("alert")).textContent).toContain("broken at entry 4");
    await user.click(screen.getByRole("button", { name: "Older entries" }));
    expect(await screen.findByRole("cell", { name: "5" })).toBeDefined();
    await user.selectOptions(screen.getByLabelText("Action"), "auth.login");
    expect(await screen.findByRole("table", { name: "Audit log entries" })).toBeDefined();
  });
});
