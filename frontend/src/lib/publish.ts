export interface PublishRecord {
  id: string;
  project_id: string;
  render_id: string;
  platform: string;
  status: string;
  external_id: string | null;
  url: string | null;
  error: string | null;
  attempts: number;
}

export async function fetchPublish(projectId: string): Promise<PublishRecord[]> {
  const res = await fetch(`/api/projects/${projectId}/publish`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
