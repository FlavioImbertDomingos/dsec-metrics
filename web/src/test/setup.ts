import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

vi.mock("echarts-for-react/esm/core", () => import("@/test/echarts-stub"));

let prefersDark = false;

export function setSystemDark(value: boolean): void {
  prefersDark = value;
}

beforeEach(() => {
  prefersDark = false;
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("dark") && prefersDark,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.className = "";
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});
