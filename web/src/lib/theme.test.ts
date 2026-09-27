import { describe, expect, it, vi } from "vitest";

import { setSystemDark } from "@/test/setup";

import { applyPreference, readPreference } from "./theme";

describe("theme", () => {
  it("defaults to system", () => {
    expect(readPreference()).toBe("system");
  });

  it("stores and applies an explicit choice", () => {
    applyPreference("dark");
    expect(readPreference()).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    applyPreference("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("follows the system when set to system", () => {
    setSystemDark(true);
    applyPreference("system");
    expect(localStorage.getItem("dsec-theme")).toBeNull();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("survives unavailable storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readPreference()).toBe("system");
    applyPreference("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
