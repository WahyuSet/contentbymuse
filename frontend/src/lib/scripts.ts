export interface ScriptSummary {
  id: string;
  project_id: string;
  idea_id: string | null;
  version: number;
  parent_id: string | null;
  source: string;
  status: string;
  title: string;
  hook: string;
  estimated_duration_s: number;
  best_score: number | null;
  edited_after_validation: boolean;
  created_at: string;
  updated_at: string;
}

export interface Scene {
  id: string;
  script_id: string;
  position: number;
  beat: string;
  voiceover: string;
  subtitle_override: string | null;
  visual_prompt: string;
  include_mascot: boolean;
  visual_type: string;
  transition: string;
  emphasis_words: string[];
  keyword_text: string | null;
  est_duration_s: number;
  revision: number;
}

export interface CheckIssue {
  code: string;
  severity: string;
  scene_position: number | null;
  message: string;
}

export interface ValidationInfo {
  id: string;
  attempt: number;
  status: string;
  score: number;
  summary: string;
  issues: {
    severity: string;
    area: string;
    scene_position: number | null;
    message: string;
    suggestion: string | null;
  }[];
  claims_to_verify: string[];
  created_at: string;
}

export interface ScriptDetail extends ScriptSummary {
  scenes: Scene[];
  checks: CheckIssue[];
  validation: ValidationInfo | null;
  claims: string[];
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `Permintaan gagal: HTTP ${response.status}`);
  }
  return response.json();
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

export function fetchScripts(projectId: string): Promise<ScriptSummary[]> {
  return api(`/api/projects/${projectId}/scripts`);
}

export function fetchScriptDetail(id: string): Promise<ScriptDetail> {
  return api(`/api/scripts/${id}`);
}

export function generateScript(
  projectId: string,
): Promise<{ job: { id: string }; created: boolean }> {
  return post(`/api/projects/${projectId}/script/generate`);
}

export function validateScript(
  scriptId: string,
): Promise<{ job: { id: string }; created: boolean }> {
  return post(`/api/scripts/${scriptId}/validate`, {});
}

export function approveScript(scriptId: string): Promise<ScriptSummary> {
  return post(`/api/scripts/${scriptId}/approve`, { claims_confirmed: true });
}

export function patchScene(
  sceneId: string,
  body: Partial<Scene>,
): Promise<{ scene: Scene; checks: CheckIssue[] }> {
  return api(`/api/scenes/${sceneId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function addScene(
  scriptId: string,
  body: { voiceover: string; visual_prompt: string },
): Promise<Scene> {
  return post(`/api/scripts/${scriptId}/scenes`, body);
}

export function deleteScene(sceneId: string): Promise<{ deleted: string }> {
  return api(`/api/scenes/${sceneId}`, { method: "DELETE" });
}

export function reorderScenes(
  scriptId: string,
  sceneIds: string[],
): Promise<ScriptDetail> {
  return post(`/api/scripts/${scriptId}/scenes/reorder`, { scene_ids: sceneIds });
}

export const BEATS = [
  "hook",
  "setup",
  "main",
  "twist",
  "impact",
  "payoff",
  "cta",
  "loop",
];

export const BEAT_LABELS: Record<string, string> = {
  twist: "Twist / Koreksi",
};

export function beatLabel(beat: string): string {
  return BEAT_LABELS[beat] ?? beat;
}

const STATUS_LABELS: Record<string, string> = {
  draft: "Draf",
  validated: "Tervalidasi",
  needs_attention: "Perlu perhatian",
  approved: "Disetujui",
};

export function scriptStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function formatDuration(seconds: number): string {
  return `±${Math.round(seconds)} detik`;
}
