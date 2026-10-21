export interface VisualStyle {
  id: string;
  name: string;
  version: number;
  style_text: string;
  negative_text: string;
  mascot_anchor: string;
  reference_asset_id: string | null;
  image_params: Record<string, unknown>;
  is_default: boolean;
}

export interface VisualStylePatch {
  name?: string;
  style_text?: string;
  negative_text?: string;
  mascot_anchor?: string;
  image_params?: Record<string, unknown>;
}

export async function fetchVisualStyles(): Promise<VisualStyle[]> {
  const response = await fetch("/api/visual-styles");
  if (!response.ok) throw new Error("Gagal memuat gaya visual");
  return (await response.json()) as VisualStyle[];
}

export async function patchVisualStyle(
  styleId: string,
  patch: VisualStylePatch,
): Promise<VisualStyle> {
  const response = await fetch(`/api/visual-styles/${styleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) throw new Error("Gagal menyimpan gaya visual");
  return (await response.json()) as VisualStyle;
}

export async function regenerateImage(sceneId: string): Promise<void> {
  const response = await fetch(`/api/scenes/${sceneId}/image/regenerate`, {
    method: "POST",
  });
  if (!response.ok) throw new Error("Gagal membuat ulang gambar");
}
