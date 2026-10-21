import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchJobs } from "./lib/jobs";
import {
  fetchMetadata,
  fetchRender,
  fetchThumbnail,
  requestRender,
} from "./lib/render";

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
  const thumbnail = useQuery({
    queryKey: ["thumbnail", projectId],
    queryFn: () => fetchThumbnail(projectId),
    refetchInterval: 5000,
  });
  const metadata = useQuery({
    queryKey: ["metadata", projectId],
    queryFn: () => fetchMetadata(projectId),
    refetchInterval: 5000,
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: fetchJobs,
    refetchInterval: 1000,
  });
  const activeRenderJob = (jobs.data ?? []).find(
    (job) =>
      job.type === "render" &&
      job.project_id === projectId &&
      (job.status === "queued" || job.status === "processing"),
  );
  const renderActive = activeRenderJob !== undefined;
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
        <>
          <p className="panel-note">
            Render sedang berjalan
            {activeRenderJob.progress_message
              ? ` — ${activeRenderJob.progress_message}`
              : ""}
          </p>
          <div className="render-progress">
            <div
              className="render-progress-bar"
              style={{ width: `${activeRenderJob.progress}%` }}
            />
          </div>
          <p className="panel-note">{activeRenderJob.progress}%</p>
        </>
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
          {thumbnail.data && (
            <>
              <h4>Thumbnail AI</h4>
              <img
                className="render-thumb"
                src={thumbnail.data.url}
                alt={thumbnail.data.title_text ?? "Thumbnail"}
              />
            </>
          )}
          {metadata.data?.title && (
            <>
              <h4>Metadata publish</h4>
              <p className="panel-note">
                <strong>{metadata.data.title}</strong>
              </p>
              <p className="panel-note">{metadata.data.description}</p>
              <p className="panel-note">
                {(metadata.data.hashtags ?? []).map((tag) => `#${tag}`).join(" ")}
              </p>
            </>
          )}
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
