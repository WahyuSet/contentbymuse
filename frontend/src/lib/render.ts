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

export interface ThumbnailInfo {
  version: number;
  url: string;
  title_text: string | null;
}

export interface MetadataInfo {
  title: string | null;
  description: string | null;
  hashtags: string[] | null;
  fb_caption: string | null;
}

export async function fetchThumbnail(projectId: string): Promise<ThumbnailInfo | null> {
  const res = await fetch(`/api/projects/${projectId}/thumbnail`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchMetadata(projectId: string): Promise<MetadataInfo | null> {
  const res = await fetch(`/api/projects/${projectId}/metadata`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
