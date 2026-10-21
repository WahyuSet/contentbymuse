export interface Job {
  id: string;
  type: string;
  status: string;
  progress: number;
  progress_message: string;
  input: { label?: string };
  result: Record<string, unknown> | null;
  error: { kind: string; message: string } | null;
  created_at: string;
  finished_at: string | null;
}

const LABELS: Record<string, string> = {
  queued: "Antre",
  processing: "Berjalan",
  completed: "Selesai",
  failed: "Gagal",
  cancelled: "Dibatalkan",
};

export function statusLabel(status: string): string {
  return LABELS[status] ?? status;
}

export async function fetchJobs(): Promise<Job[]> {
  const response = await fetch("/api/jobs");
  if (!response.ok) throw new Error(`Gagal memuat job: HTTP ${response.status}`);
  return response.json();
}

export async function enqueueDemoJob(label: string): Promise<Job> {
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      type: "provider_test",
      input: { label, sleep_ms: 1200 },
    }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `Gagal membuat job: HTTP ${response.status}`);
  }
  return response.json();
}
