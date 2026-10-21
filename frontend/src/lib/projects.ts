export interface Category {
  id: string;
  slug: string;
  name: string;
  description: string;
  fact_check: string;
  enabled: boolean;
}

export interface Format {
  id: string;
  slug: string;
  name: string;
  description: string;
  enabled: boolean;
}

export interface Project {
  id: string;
  title: string;
  topic: string | null;
  category_id: string | null;
  category_source: string | null;
  format_id: string | null;
  language: string;
  target_min_s: number;
  target_max_s: number;
  selected_idea_id: string | null;
  idea_batches: number;
  idea_count: number;
  created_at: string;
  updated_at: string;
}

export interface Idea {
  id: string;
  project_id: string;
  batch: number;
  position: number;
  title: string;
  angle: string;
  hook: string;
  why_it_works: string;
  suggested_category_slug: string | null;
  fact_risk: string | null;
  fact_note: string | null;
  created_at: string;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `Permintaan gagal: HTTP ${response.status}`);
  }
  return response.json();
}

export function fetchCategories(): Promise<Category[]> {
  return api("/api/categories");
}

export function fetchFormats(): Promise<Format[]> {
  return api("/api/formats");
}

export function fetchProjects(): Promise<Project[]> {
  return api("/api/projects");
}

export function fetchProject(id: string): Promise<Project> {
  return api(`/api/projects/${id}`);
}

export function fetchIdeas(projectId: string): Promise<Idea[]> {
  return api(`/api/projects/${projectId}/ideas`);
}

export function createProject(body: {
  topic?: string;
  category_id?: string;
  format_id?: string;
}): Promise<Project> {
  return api("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function generateIdeas(
  projectId: string,
): Promise<{ job: { id: string; status: string }; created: boolean }> {
  return api(`/api/projects/${projectId}/ideas/generate`, { method: "POST" });
}

export function selectIdea(ideaId: string): Promise<Project> {
  return api(`/api/ideas/${ideaId}/select`, { method: "POST" });
}

export function groupByBatch(ideas: Idea[]): Map<number, Idea[]> {
  const groups = new Map<number, Idea[]>();
  for (const idea of ideas) {
    const list = groups.get(idea.batch) ?? [];
    list.push(idea);
    groups.set(idea.batch, list);
  }
  for (const list of groups.values()) {
    list.sort((a, b) => a.position - b.position);
  }
  return new Map([...groups.entries()].sort((a, b) => a[0] - b[0]));
}

export function batchLabel(batch: number): string {
  return `Batch ${batch}`;
}
