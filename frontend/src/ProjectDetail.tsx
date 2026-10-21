import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJobs } from "./lib/jobs";
import ScriptPanel from "./ScriptPanel";
import VisualStylePanel from "./VisualStylePanel";
import VoiceSettings from "./VoiceSettings";
import {
  batchLabel,
  fetchIdeas,
  fetchProject,
  generateIdeas,
  groupByBatch,
  selectIdea,
  type Idea,
} from "./lib/projects";

export default function ProjectDetail({
  projectId,
  onBack,
}: {
  projectId: string;
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
    refetchInterval: 1000,
  });
  const ideas = useQuery({
    queryKey: ["ideas", projectId],
    queryFn: () => fetchIdeas(projectId),
    refetchInterval: 1000,
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: fetchJobs,
    refetchInterval: 1000,
  });

  const generate = useMutation({
    mutationFn: () => generateIdeas(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ideas", projectId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const select = useMutation({
    mutationFn: (ideaId: string) => selectIdea(ideaId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const activeIdeasJob = jobs.data?.find(
    (job) =>
      job.project_id === projectId &&
      job.type === "ideas" &&
      (job.status === "queued" || job.status === "processing"),
  );
  const failedIdeasJob = jobs.data?.find(
    (job) => job.project_id === projectId && job.type === "ideas" && job.status === "failed",
  );
  const batches = ideas.data ? groupByBatch(ideas.data) : new Map<number, Idea[]>();
  const selectedId = project.data?.selected_idea_id;

  return (
    <>
      <p>
        <button type="button" className="link-button" onClick={onBack}>
          ← Semua project
        </button>
      </p>
      {project.isPending && <p>Memuat…</p>}
      {project.isError && (
        <p className="error-text">Project tidak bisa dimuat. Coba kembali ke daftar.</p>
      )}
      {project.data && (
        <section className="panel">
          <h2>{project.data.title}</h2>
          <p className="panel-note">
            {project.data.topic
              ? `Topik: ${project.data.topic}`
              : "Tanpa topik — ide ditemukan dari kategori."}
            {" · "}Bahasa: {project.data.language}
            {" · "}Target {project.data.target_min_s}–{project.data.target_max_s} detik
            {project.data.category_source === "suggested"
              ? " · Kategori ditebak dari ide terpilih"
              : ""}
          </p>
          <button
            type="button"
            className="primary-action"
            disabled={generate.isPending || Boolean(activeIdeasJob)}
            onClick={() => generate.mutate()}
          >
            {activeIdeasJob
              ? "Ide sedang dibuat…"
              : project.data.idea_batches > 0
                ? "Buat batch ide baru"
                : "Buat 8 ide"}
          </button>
          {generate.isError && (
            <p className="error-text">{(generate.error as Error).message}</p>
          )}
          {!activeIdeasJob && failedIdeasJob?.error && (
            <p className="error-text">
              Pembuatan ide terakhir gagal: {failedIdeasJob.error.message}
            </p>
          )}
        </section>
      )}

      {ideas.data && ideas.data.length === 0 && !activeIdeasJob && (
        <section className="panel">
          <p>Belum ada ide. Klik “Buat 8 ide” untuk batch pertama.</p>
        </section>
      )}

      {[...batches.entries()].map(([batch, batchIdeas]) => (
        <section className="panel" key={batch}>
          <h2>{batchLabel(batch)}</h2>
          <div className="idea-grid">
            {batchIdeas.map((idea) => (
              <article className="idea-card" key={idea.id}>
                <p className="idea-position">Ide {idea.position}</p>
                <h3>{idea.title}</h3>
                <p className="idea-hook">“{idea.hook}”</p>
                <p>{idea.angle}</p>
                <p className="idea-why">{idea.why_it_works}</p>
                {idea.fact_risk === "check" && (
                  <p className="fact-note">
                    <strong>Perlu dicek:</strong> {idea.fact_note}
                  </p>
                )}
                {selectedId === idea.id ? (
                  <span className="badge badge-completed">Ide terpilih</span>
                ) : (
                  <button
                    type="button"
                    disabled={select.isPending}
                    onClick={() => select.mutate(idea.id)}
                  >
                    Pilih ide ini
                  </button>
                )}
              </article>
            ))}
          </div>
          {select.isError && (
            <p className="error-text">{(select.error as Error).message}</p>
          )}
        </section>
      ))}

      {project.data && <VoiceSettings project={project.data} />}

      {project.data && <VisualStylePanel project={project.data} />}

      {project.data && (
        <ScriptPanel
          projectId={projectId}
          selectedIdeaId={project.data.selected_idea_id}
          activeScriptId={project.data.active_script_id}
        />
      )}
    </>
  );
}
