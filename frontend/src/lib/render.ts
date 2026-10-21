export interface RenderInfo {
  version: number;
  duration_s: number | null;
  encoder: string | null;
  warnings: string[];
  files: Record<string, string>;
  created_at: string;
}

export async function fetchRender(
  projectId: string,
): Promise<RenderInfo | null> {
  const response = await fetch(`/api/projects/${projectId}/render`);
  if (!response.ok) throw new Error("Gagal memuat render");
  return (await response.json()) as RenderInfo | null;
}

export async function requestRender(
  projectId: string,
  force: boolean,
): Promise<void> {
  const response = await fetch(`/api/projects/${projectId}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new Error(body?.error?.message ?? "Gagal meminta render");
  }
}
