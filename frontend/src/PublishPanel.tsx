import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchPublish,
  retryPublish,
  type PublishRecord,
} from "./lib/publish";

const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube Shorts",
  facebook: "Facebook Reels",
};

const STATUS_LABELS: Record<string, string> = {
  queued: "Mengantre penyiapan paket",
  awaiting_upload: "Siap diupload agen",
  uploading: "Sedang diupload",
  published: "Terbit",
  failed: "Gagal",
  superseded: "Digantikan render baru",
};

function PublishRow({
  record,
  onRetry,
}: {
  record: PublishRecord;
  onRetry: (id: string) => void;
}) {
  return (
    <li>
      <strong>{PLATFORM_LABELS[record.platform] ?? record.platform}</strong>
      {" — "}
      {STATUS_LABELS[record.status] ?? record.status}
      {record.status === "published" && record.url && (
        <>
          {" · "}
          <a href={record.url} target="_blank" rel="noreferrer">
            Lihat video
          </a>
        </>
      )}
      {record.status === "failed" && record.error && (
        <p className="error-text">{record.error}</p>
      )}
      {record.status === "failed" && (
        <button type="button" onClick={() => onRetry(record.id)}>
          Coba lagi
        </button>
      )}
    </li>
  );
}

export default function PublishPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: retryPublish,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["publish", projectId] }),
  });
  const publish = useQuery({
    queryKey: ["publish", projectId],
    queryFn: () => fetchPublish(projectId),
    refetchInterval: 5000,
  });
  const records = publish.data ?? [];
  if (records.length === 0) return null;
  return (
    <section className="panel">
      <h3>Publish</h3>
      <ul className="publish-list">
        {records.map((record) => (
          <PublishRow
            key={record.id}
            record={record}
            onRetry={(id) => retry.mutate(id)}
          />
        ))}
      </ul>
    </section>
  );
}
