import { describe, expect, it } from "vitest";

import { BEATS, beatLabel, formatDuration, scriptStatusLabel } from "./scripts";

describe("scriptStatusLabel", () => {
  it("memetakan semua status script ke Bahasa Indonesia", () => {
    expect(scriptStatusLabel("draft")).toBe("Draf");
    expect(scriptStatusLabel("validated")).toBe("Tervalidasi");
    expect(scriptStatusLabel("needs_attention")).toBe("Perlu perhatian");
    expect(scriptStatusLabel("approved")).toBe("Disetujui");
    expect(scriptStatusLabel("aneh")).toBe("aneh");
  });
});

describe("BEATS", () => {
  it("memuat twist tepat satu kali, sesudah main dan sebelum impact", () => {
    expect(BEATS.filter((beat) => beat === "twist")).toHaveLength(1);
    expect(BEATS.indexOf("twist")).toBeGreaterThan(BEATS.indexOf("main"));
    expect(BEATS.indexOf("twist")).toBeLessThan(BEATS.indexOf("impact"));
  });

  it("tetap memuat semua beat lama", () => {
    for (const beat of ["hook", "setup", "main", "impact", "payoff", "cta", "loop"]) {
      expect(BEATS).toContain(beat);
    }
  });
});

describe("beatLabel", () => {
  it("memetakan twist ke label Twist / Koreksi", () => {
    expect(beatLabel("twist")).toBe("Twist / Koreksi");
  });

  it("mengembalikan beat mentah sebagai fallback", () => {
    expect(beatLabel("hook")).toBe("hook");
  });
});

describe("formatDuration", () => {
  it("membulatkan ke detik terdekat dengan tanda ±", () => {
    expect(formatDuration(33.7)).toBe("±34 detik");
    expect(formatDuration(30)).toBe("±30 detik");
  });
});
