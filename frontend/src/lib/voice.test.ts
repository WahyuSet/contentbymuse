import { describe, expect, it } from "vitest";

import { timingsLabel, type SceneAsset } from "./voice";

function asset(partial: Partial<SceneAsset>): SceneAsset {
  return {
    id: "a1",
    project_id: "p1",
    scene_id: "s1",
    kind: "word_timings",
    version: 1,
    mime: "application/json",
    size_bytes: 0,
    duration_s: null,
    data: null,
    input_hash: "h",
    provider_id: null,
    model: null,
    is_selected: true,
    created_at: "2026-10-21T00:00:00Z",
    url: "",
    ...partial,
  };
}

describe("timingsLabel", () => {
  it("memformat metode dan jumlah kata", () => {
    const timings = asset({
      data: {
        words: [
          { word: "a", start: 0, end: 0.4 },
          { word: "b", start: 0.4, end: 0.8 },
        ],
        method: "provider",
      },
    });
    expect(timingsLabel(timings)).toBe("Timing kata: dari provider · 2 kata");
    const whisper = asset({
      data: { words: [{ word: "a", start: 0, end: 0.4 }], method: "whisper:small" },
    });
    expect(timingsLabel(whisper)).toBe("Timing kata: Whisper (small) · 1 kata");
    const proportional = asset({
      data: { words: [], method: "proportional" },
    });
    expect(timingsLabel(proportional)).toBe("Timing kata: perkiraan proporsional · 0 kata");
  });

  it("mengembalikan null tanpa aset timing", () => {
    expect(timingsLabel(null)).toBeNull();
    expect(timingsLabel(undefined)).toBeNull();
  });
});
