import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

let prefersDark = false;

export function setSystemDark(value: boolean): void {
  prefersDark = value;
}

beforeEach(() => {
  prefersDark = false;
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
  vi.unstubAllGlobals();
});
