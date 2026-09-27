import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Link, match, navigate, useLocation, withQuery } from "@/lib/router";

function Where() {
  const { path, search } = useLocation();
  return <p>{`${path}|${search.toString()}`}</p>;
}

describe("router", () => {
  it("matches patterns and decodes parameters", () => {
    expect(match("/metrics/:id", "/metrics/KRI-01")).toEqual({ id: "KRI-01" });
    expect(match("/metrics/:id", "/metrics/a%20b")).toEqual({ id: "a b" });
    expect(match("/metrics/:id", "/metrics")).toBeNull();
    expect(match("/metrics/:id", "/controls/x")).toBeNull();
    expect(match("/metrics/:id", "/metrics/%E0%A4%A")).toBeNull();
  });

  it("builds query strings without empty values", () => {
    expect(withQuery("/x", { a: "1", b: undefined, c: "" })).toBe("/x?a=1");
    expect(withQuery("/x", {})).toBe("/x");
  });

  it("navigates in place on plain clicks and follows history", async () => {
    const user = userEvent.setup();
    render(
      <>
        <Where />
        <Link to="/metrics?type=kri">Metrics</Link>
      </>,
    );
    expect(screen.getByText("/|")).toBeDefined();
    await user.click(screen.getByRole("link", { name: "Metrics" }));
    expect(screen.getByText("/metrics|type=kri")).toBeDefined();
    act(() => {
      navigate("/controls", { replace: true });
    });
    expect(screen.getByText("/controls|")).toBeDefined();
  });

  it("leaves modified clicks to the browser", () => {
    render(<Link to="/elsewhere">Away</Link>);
    const link = screen.getByRole("link", { name: "Away" });
    let preventedByLink: boolean | null = null;
    const after = (e: Event) => {
      preventedByLink = e.defaultPrevented;
      e.preventDefault(); // stop jsdom from trying to load the page
    };
    document.addEventListener("click", after);
    link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true }));
    document.removeEventListener("click", after);
    expect(preventedByLink).toBe(false);
  });
});
