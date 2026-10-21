import { describe, expect, it } from "vitest";

import { statusLabel } from "./jobs";

describe("statusLabel", () => {
  it("memetakan semua status job ke Bahasa Indonesia", () => {
    expect(statusLabel("queued")).toBe("Antre");
    expect(statusLabel("processing")).toBe("Berjalan");
    expect(statusLabel("completed")).toBe("Selesai");
    expect(statusLabel("failed")).toBe("Gagal");
    expect(statusLabel("cancelled")).toBe("Dibatalkan");
  });

  it("mengembalikan status tak dikenal apa adanya", () => {
    expect(statusLabel("aneh")).toBe("aneh");
  });
});
