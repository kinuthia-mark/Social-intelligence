import { afterEach, describe, expect, it, vi } from "vitest";
import { cn, compact, initials, pct, timeAgo } from "./utils";
import { toCsv } from "./csv";

describe("compact", () => {
  it("leaves small numbers alone", () => expect(compact(999)).toBe("999"));
  it("uses K, M and B", () => {
    expect(compact(1840)).toBe("1.8K");
    expect(compact(1_200_000)).toBe("1.2M");
    expect(compact(3_400_000_000)).toBe("3.4B");
  });
  it("drops the decimal for round values", () => expect(compact(2000)).toBe("2K"));
  it("handles negatives", () => expect(compact(-1500)).toBe("-1.5K"));
});

describe("pct", () => {
  it("adds a plus sign to gains only", () => {
    expect(pct(12.44)).toBe("+12.4%");
    expect(pct(-4)).toBe("-4.0%");
    expect(pct(0)).toBe("0.0%");
  });
});

describe("initials", () => {
  it("takes the first letters of the first two words", () => {
    expect(initials("Ochiengs Moses")).toBe("OM");
    expect(initials("ada lovelace king")).toBe("AL");
  });
});

describe("cn", () => {
  it("joins truthy class names", () => expect(cn("a", false, null, "b", undefined)).toBe("a b"));
});

describe("timeAgo", () => {
  afterEach(() => vi.useRealTimers());

  it("formats minutes, hours and days", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T12:00:00Z"));
    expect(timeAgo("2026-06-12T11:59:40Z")).toBe("just now");
    expect(timeAgo("2026-06-12T11:45:00Z")).toBe("15m");
    expect(timeAgo("2026-06-12T09:00:00Z")).toBe("3h");
    expect(timeAgo("2026-06-10T12:00:00Z")).toBe("2d");
  });
});

describe("toCsv", () => {
  it("writes a header row and quotes values that need it", () => {
    const csv = toCsv([
      { name: "Maren Cole", text: 'Said "wow", loved it' },
      { name: "Sam", text: "line\nbreak" },
    ]);
    expect(csv).toBe('name,text\nMaren Cole,"Said ""wow"", loved it"\nSam,"line\nbreak"');
  });

  it("returns an empty string for no rows", () => expect(toCsv([])).toBe(""));
});
