import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { enqueueDemoJob, fetchJobs, statusLabel } from "./lib/jobs";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("id-ID", { hour12: false });
}

export default function App() {
  const [label, setLabel] = useState("");
  const queryClient = useQueryClient();
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: fetchJobs,
    refetchInterval: 1000,
  });
  const enqueue = useMutation({
    mutationFn: () => enqueueDemoJob(label.trim() || "job contoh"),
    onSuccess: () => {
      setLabel("");
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    enqueue.mutate();
  }

  return (
    <div className="page">
      <header className="masthead">
        <span className="mascot-head" aria-hidden="true" />
        <div>
          <h1>Stickman Content Factory</h1>
          <p>Antrean produksi @SiKlepon-id — Fase 1: kerangka berjalan (provider fake).</p>
        </div>
      </header>

      <section className="panel">
        <h2>Job contoh</h2>
        <p className="panel-note">
          Mengantrekan satu job <code>provider_test</code>. Worker mengambilnya dari
          antrean, memanggil provider fake, lalu menandainya selesai — alur yang sama
          yang nanti dipakai tahap produksi beneran.
        </p>
        <form onSubmit={onSubmit} className="enqueue-form">
          <input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="Label job, mis. cek pagi"
            aria-label="Label job"
          />
          <button type="submit" disabled={enqueue.isPending}>
            {enqueue.isPending ? "Mengantrekan…" : "Jalankan job contoh"}
          </button>
        </form>
        {enqueue.isError && (
          <p className="error-text">{(enqueue.error as Error).message}</p>
        )}
      </section>

      <section className="panel">
        <h2>Antrean job</h2>
        {jobs.isPending && <p>Memuat…</p>}
        {jobs.isError && (
          <p className="error-text">
            API tidak terjangkau. Pastikan backend jalan di 127.0.0.1:8010.
          </p>
        )}
        {jobs.data && jobs.data.length === 0 && (
          <p>Belum ada job. Jalankan job contoh pertama di atas.</p>
        )}
        {jobs.data && jobs.data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Dibuat</th>
                <th>Tipe</th>
                <th>Label</th>
                <th>Status</th>
                <th>Progres</th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.map((job) => (
                <tr key={job.id}>
                  <td>{formatTime(job.created_at)}</td>
                  <td>
                    <code>{job.type}</code>
                  </td>
                  <td>{job.input.label ?? "—"}</td>
                  <td>
                    <span className={`badge badge-${job.status}`}>
                      {statusLabel(job.status)}
                    </span>
                  </td>
                  <td>{job.status === "completed" ? 100 : job.progress}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
