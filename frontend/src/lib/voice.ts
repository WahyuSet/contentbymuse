export interface SceneAsset {
  id: string;
  project_id: string | null;
  scene_id: string | null;
  kind: string;
  version: number;
  mime: string;
  size_bytes: number;
  duration_s: number | null;
  data: {
    words?: { word: string; start: number; end: number }[];
    method?: string;
    clip_asset_id?: string;
    trim?: { start_s: number; end_s: number } | null;
  } | null;
  input_hash: string;
  provider_id: string | null;
  model: string | null;
  is_selected: boolean;
  created_at: string;
  url: string;
}

export interface ProviderVoice {
  id: string;
  name: string;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `Permintaan gagal: HTTP ${response.status}`);
  }
  return response.json();
}

export function fetchSceneAssets(sceneId: string): Promise<SceneAsset[]> {
  return api(`/api/scenes/${sceneId}/assets`);
}

export function fetchProviderVoices(providerId: string): Promise<ProviderVoice[]> {
  return api(`/api/providers/${providerId}/voices`);
}

export function regenerateVoice(
  sceneId: string,
): Promise<{ job: { id: string }; created: boolean }> {
  return api(`/api/scenes/${sceneId}/voice/regenerate`, { method: "POST" });
}

export function fetchProviders(): Promise<
  { id: string; name: string; capability: string; enabled: boolean }[]
> {
  return api(`/api/providers`);
}

export function timingsLabel(timings: SceneAsset | null | undefined): string | null {
  if (!timings || !timings.data) return null;
  const count = timings.data.words?.length ?? 0;
  const method = timings.data.method ?? "";
  let methodLabel = method;
  if (method === "provider") methodLabel = "dari provider";
  else if (method === "proportional") methodLabel = "perkiraan proporsional";
  else if (method.startsWith("whisper:")) {
    methodLabel = `Whisper (${method.slice("whisper:".length)})`;
  }
  return `Timing kata: ${methodLabel} · ${count} kata`;
}
