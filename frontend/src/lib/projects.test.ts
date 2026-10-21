import { describe, expect, it } from "vitest";

import { batchLabel, groupByBatch, type Idea } from "./projects";

function idea(batch: number, position: number): Idea {
  return {
    id: `i-${batch}-${position}`,
    project_id: "p1",
    batch,
    position,
    title: `Judul ${batch}-${position}`,
    angle: "sudut",
    hook: "hook",
    why_it_works: "alasan",
    suggested_category_slug: null,
    fact_risk: "low",
    fact_note: null,
    created_at: "2026-10-21T00:00:00Z",
  };
}

describe("groupByBatch", () => {
  it("mengelompokkan per batch terurut dan posisi terurut", () => {
    const groups = groupByBatch([idea(2, 1), idea(1, 2), idea(1, 1)]);
    expect([...groups.keys()]).toEqual([1, 2]);
    expect(groups.get(1)?.map((i) => i.position)).toEqual([1, 2]);
  });

  it("daftar kosong menghasilkan nol batch", () => {
    expect(groupByBatch([]).size).toBe(0);
  });
});

describe("batchLabel", () => {
  it("memberi label batch", () => {
    expect(batchLabel(3)).toBe("Batch 3");
  });
});
