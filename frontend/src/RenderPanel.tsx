import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchJobs } from "./lib/jobs";
import { fetchRender, requestRender } from "./lib/render";

const FILE_LABELS: Record<string, string> = {
  video: "video.mp4",
  srt: "subtitles.srt",
  ass: "subtitles.ass",
  thumbnail: "thumbnail.jpg",
};

export default function RenderPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const render = useQuery({
    queryKey: ["render", projectId],
    queryFn: () => fetchRender(projectId),
    refetchInterval: 2000,
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: fetchJobs,
    refetchInterval: 1000,
  });
  const renderActive = (jobs.data ?? []).some(
    (job) =>
      job.type === "render" &&
      job.project_id === projectId &&
      (job.status === "queued" || job.status === "processing"),
  );
  const start = useMutation({
    mutationFn: (force: boolean) => requestRender(projectId, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["render", projectId] });
    },
  });
  const info = render.data;

  return (
    <section className="panel">
      <h2>Render</h2>
      {renderActive && (
        <p className="panel-note">
          Render sedang berjalan — video 9:16 dibuat dari gambar, suara, dan
          subtitle scene. Di mesin tanpa GPU proses ini bisa makan beberapa
          menit.
        </p>
      )}
      {info ? (
        <>
          <video
            className="render-player"
            controls
            src={info.files.video}
            poster={info.files.thumbnail}
            preload="metadata"
          />
          <p className="panel-note">
            Versi {info.version}
            {info.duration_s ? ` · ${info.duration_s.toFixed(1)} detik` : ""}
            {info.encoder ? ` · encoder ${info.encoder}` : ""}
          </p>
          {info.warnings.map((warning) => (
            <p key={warning} className="error-text">
              {warning}
            </p>
          ))}
          <div className="render-downloads">
            {Object.entries(info.files).map(([name, url]) => (
              <a key={name} href={url} download>
                Unduh {FILE_LABELS[name] ?? name}
              </a>
            ))}
          </div>
        </>
      ) : (
        <p className="panel-note">
          Belum ada video. Render dibuat otomatis setelah semua scene punya
          suara dan gambar, atau mulai manual di bawah.
        </p>
      )}
      <div className="scene-actions">
        <button
          type="button"
          disabled={renderActive || start.isPending}
          onClick={() => start.mutate(false)}
        >
          Render sekarang
        </button>
        {info && (
          <button
            type="button"
            disabled={renderActive || start.isPending}
            onClick={() => start.mutate(true)}
          >
            Render ulang paksa
          </button>
        )}
      </div>
      {start.isError && (
        <p className="error-text">{(start.error as Error).message}</p>
      )}
    </section>
  );
}
