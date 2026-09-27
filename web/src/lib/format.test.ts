import { describe, expect, it } from "vitest";

import {
  deltaTone,
  formatDate,
  formatDelta,
  formatMonth,
  formatValue,
  humanize,
  shortHash,
} from "@/lib/format";

describe("format", () => {
  it("formats values by unit", () => {
    expect(formatValue(null, "count")).toBe("—");
    expect(formatValue(98.444, "percent")).toBe("98.44%");
    expect(formatValue(1, "days")).toBe("1 day");
    expect(formatValue(11, "days")).toBe("11 days");
    expect(formatValue(1200, "count")).toBe("1,200");
    expect(formatValue(1.5, "count")).toBe("1.5");
    expect(formatValue(5.061, "ratio")).toBe("5.06");
  });

  it("formats changes and their direction", () => {
    expect(formatDelta(null, "count")).toBeNull();
    expect(formatDelta(0, "count")).toBe("no change");
    expect(formatDelta(2, "count")).toBe("+2");
    expect(formatDelta(-0.94, "percent")).toBe("−0.94 pts");
    expect(deltaTone(1, false)).toBe("worse");
    expect(deltaTone(-1, false)).toBe("better");
    expect(deltaTone(1, true)).toBe("better");
    expect(deltaTone(0, true)).toBe("neutral");
  });

  it("formats dates, names and hashes", () => {
    expect(formatDate("2026-09-30")).toBe("Sep 30, 2026");
    expect(formatDate("2026-09-30T23:00:00Z")).toBe("Sep 30, 2026");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not a date")).toBe("not a date");
    expect(formatMonth("2026-09-30")).toBe("Sep 26");
    expect(formatMonth("junk")).toBe("junk");
    expect(humanize("business_unit")).toBe("Business unit");
    expect(shortHash("abcdef0123456789")).toBe("abcdef012345");
  });
});
