import { describe, expect, it } from "vitest";

import { formatDuration, scriptStatusLabel } from "./scripts";

describe("scriptStatusLabel", () => {
  it("memetakan semua status script ke Bahasa Indonesia", () => {
    expect(scriptStatusLabel("draft")).toBe("Draf");
    expect(scriptStatusLabel("validated")).toBe("Tervalidasi");
    expect(scriptStatusLabel("needs_attention")).toBe("Perlu perhatian");
    expect(scriptStatusLabel("approved")).toBe("Disetujui");
    expect(scriptStatusLabel("aneh")).toBe("aneh");
  });
});

describe("formatDuration", () => {
  it("membulatkan ke detik terdekat dengan tanda ±", () => {
    expect(formatDuration(33.7)).toBe("±34 detik");
    expect(formatDuration(30)).toBe("±30 detik");
  });
});
