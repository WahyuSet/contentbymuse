import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { regenerateImage as regenerateImageRequest } from "./lib/images";
import { fetchJobs } from "./lib/jobs";
import {
  fetchSceneAssets,
  regenerateVoice,
  timingsLabel,
} from "./lib/voice";
import {
  addScene,
  approveScript,
  deleteScene,
  fetchScriptDetail,
  fetchScripts,
  formatDuration,
  generateScript,
  patchScene,
  reorderScenes,
  scriptStatusLabel,
  validateScript,
  type Scene,
} from "./lib/scripts";

const CHAIN_TYPES = ["script", "checks_fix", "validate", "revise"];
const BEATS = ["hook", "setup", "main", "payoff", "cta", "loop"];

function SceneRow({
  scene,
  editable,
  isFirst,
  isLast,
  onMove,
  showVoice,
  voiceBusy,
  imageBusy,
}: {
  scene: Scene;
  editable: boolean;
  isFirst: boolean;
  isLast: boolean;
  onMove: (scene: Scene, direction: -1 | 1) => void;
  showVoice: boolean;
  voiceBusy: boolean;
  imageBusy: boolean;
}) {
  const queryClient = useQueryClient();
  const [voiceover, setVoiceover] = useState(scene.voiceover);
  const [visualPrompt, setVisualPrompt] = useState(scene.visual_prompt);
  const [beat, setBeat] = useState(scene.beat);
  const [mascot, setMascot] = useState(scene.include_mascot);

  useEffect(() => {
    setVoiceover(scene.voiceover);
    setVisualPrompt(scene.visual_prompt);
    setBeat(scene.beat);
    setMascot(scene.include_mascot);
  }, [scene]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["script-detail", scene.script_id] });
    queryClient.invalidateQueries({ queryKey: ["scripts"] });
  };
  const save = useMutation({
    mutationFn: () =>
      patchScene(scene.id, {
        voiceover,
        visual_prompt: visualPrompt,
        beat,
        include_mascot: mascot,
      }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => deleteScene(scene.id),
    onSuccess: invalidate,
  });
  const assets = useQuery({
    queryKey: ["scene-assets", scene.id],
    queryFn: () => fetchSceneAssets(scene.id),
    enabled: showVoice,
    refetchInterval: 1000,
  });
  const clip = assets.data?.find((a) => a.kind === "voice_clip" && a.is_selected);
  const timings = assets.data?.find(
    (a) => a.kind === "word_timings" && a.is_selected,
  );
  const image = assets.data?.find((a) => a.kind === "image" && a.is_selected);
  const regen = useMutation({
    mutationFn: () => regenerateVoice(scene.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scene-assets", scene.id] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const regenImage = useMutation({
    mutationFn: () => regenerateImageRequest(scene.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scene-assets", scene.id] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const dirty =
    voiceover !== scene.voiceover ||
    visualPrompt !== scene.visual_prompt ||
    beat !== scene.beat ||
    mascot !== scene.include_mascot;

  return (
    <div className="scene-row">
      <div className="scene-head">
        <strong>Scene {scene.position}</strong>
        <span className="project-meta">
          {formatDuration(scene.est_duration_s)}
          {scene.revision > 0 ? ` · diubah ${scene.revision}×` : ""}
        </span>
        <span className="scene-moves">
          <button type="button" disabled={!editable || isFirst} onClick={() => onMove(scene, -1)}>
            Naik
          </button>
          <button type="button" disabled={!editable || isLast} onClick={() => onMove(scene, 1)}>
            Turun
          </button>
        </span>
      </div>
      <label>
        Beat
        <select value={beat} disabled={!editable} onChange={(e) => setBeat(e.target.value)}>
          {BEATS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      <label>
        Narasi (voiceover)
        <textarea
          value={voiceover}
          disabled={!editable}
          rows={2}
          onChange={(e) => setVoiceover(e.target.value)}
        />
      </label>
      <label>
        Prompt visual (Inggris)
        <input
          value={visualPrompt}
          disabled={!editable}
          onChange={(e) => setVisualPrompt(e.target.value)}
        />
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={mascot}
          disabled={!editable}
          onChange={(e) => setMascot(e.target.checked)}
        />
        Maskot tampil di scene ini
      </label>
      {editable && (
        <div className="scene-actions">
          <button type="button" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Menyimpan…" : "Simpan scene"}
          </button>
          <button type="button" disabled={remove.isPending} onClick={() => remove.mutate()}>
            Hapus
          </button>
        </div>
      )}
      {save.isError && <p className="error-text">{(save.error as Error).message}</p>}
      {remove.isError && <p className="error-text">{(remove.error as Error).message}</p>}
      {showVoice && (
        <div className="scene-voice">
          {clip ? (
            <>
              <audio controls src={clip.url} preload="metadata" />
              <p className="panel-note">
                Klip suara versi {clip.version}
                {clip.duration_s ? ` · ${clip.duration_s.toFixed(1)} detik` : ""}
              </p>
            </>
          ) : (
            <p className="panel-note">
              {voiceBusy ? "Suara sedang dibuat…" : "Suara belum dibuat."}
            </p>
          )}
          {timings && <p className="panel-note">{timingsLabel(timings)}</p>}
          <button
            type="button"
            disabled={voiceBusy || regen.isPending}
            onClick={() => regen.mutate()}
          >
            Buat ulang suara
          </button>
          {regen.isError && (
            <p className="error-text">{(regen.error as Error).message}</p>
          )}
        </div>
      )}
      {showVoice && (
        <div className="scene-image">
          {image ? (
            <>
              <img src={image.url} alt={`Gambar scene ${scene.position}`} />
              <p className="panel-note">Gambar versi {image.version}</p>
            </>
          ) : (
            <p className="panel-note">
              {imageBusy ? "Gambar sedang dibuat…" : "Gambar belum dibuat."}
            </p>
          )}
          <button
            type="button"
            disabled={imageBusy || regenImage.isPending}
            onClick={() => regenImage.mutate()}
          >
            Buat ulang gambar
          </button>
          {regenImage.isError && (
            <p className="error-text">{(regenImage.error as Error).message}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function ScriptPanel({
  projectId,
  selectedIdeaId,
  activeScriptId,
}: {
  projectId: string;
  selectedIdeaId: string | null;
  activeScriptId: string | null;
}) {
  const queryClient = useQueryClient();
  const [viewedId, setViewedId] = useState<string | null>(null);
  const [checkedClaims, setCheckedClaims] = useState<Set<string>>(new Set());
  const [newVoiceover, setNewVoiceover] = useState("");
  const [newVisual, setNewVisual] = useState("");

  const scripts = useQuery({
    queryKey: ["scripts", projectId],
    queryFn: () => fetchScripts(projectId),
    refetchInterval: 1000,
  });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: fetchJobs, refetchInterval: 1000 });
  const busyByType = (types: string[]) =>
    new Set(
      (jobs.data ?? [])
        .filter(
          (job) =>
            types.includes(job.type) &&
            (job.status === "queued" || job.status === "processing") &&
            job.scene_id,
        )
        .map((job) => job.scene_id as string),
    );
  const busyVoiceSceneIds = busyByType(["voice", "align"]);
  const busyImageSceneIds = busyByType(["image"]);
  const chainActive = jobs.data?.some(
    (job) =>
      job.project_id === projectId &&
      CHAIN_TYPES.includes(job.type) &&
      (job.status === "queued" || job.status === "processing"),
  );

  const detailId = viewedId ?? activeScriptId ?? scripts.data?.[0]?.id ?? null;
  const detail = useQuery({
    queryKey: ["script-detail", detailId],
    queryFn: () => fetchScriptDetail(detailId as string),
    enabled: detailId !== null,
    refetchInterval: 1000,
  });

  useEffect(() => {
    setCheckedClaims(new Set());
  }, [detailId]);

  // Centang klaim diikat ke bunyi klaimnya, bukan posisi: bila polling membawa
  // rumusan klaim baru, klaim itu mulai dari keadaan belum tercentang.
  const claimTexts = detail.data?.claims ?? [];
  const allClaimsChecked =
    claimTexts.length > 0 && claimTexts.every((claim) => checkedClaims.has(claim));

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["scripts", projectId] });
    queryClient.invalidateQueries({ queryKey: ["script-detail", detailId] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
  };
  const generate = useMutation({
    mutationFn: () => generateScript(projectId),
    onSuccess: invalidateAll,
  });
  const revalidate = useMutation({
    mutationFn: () => validateScript(detailId as string),
    onSuccess: invalidateAll,
  });
  const approve = useMutation({
    mutationFn: () => approveScript(detailId as string),
    onSuccess: invalidateAll,
  });
  const add = useMutation({
    mutationFn: () =>
      addScene(detailId as string, {
        voiceover: newVoiceover.trim(),
        visual_prompt: newVisual.trim(),
      }),
    onSuccess: () => {
      setNewVoiceover("");
      setNewVisual("");
      invalidateAll();
    },
  });
  const move = (scene: Scene, direction: -1 | 1) => {
    if (!detail.data) return;
    const scenes = detail.data.scenes;
    const index = scenes.findIndex((s) => s.id === scene.id);
    const swapWith = index + direction;
    if (swapWith < 0 || swapWith >= scenes.length) return;
    const ids = scenes.map((s) => s.id);
    [ids[index], ids[swapWith]] = [ids[swapWith], ids[index]];
    reorderScenes(detail.data.id, ids).then(invalidateAll);
  };

  const data = detail.data;
  const editable = Boolean(data && activeScriptId === data.id && !chainActive);

  return (
    <section className="panel">
      <h2>Naskah (script)</h2>
      {!selectedIdeaId && <p>Pilih ide dulu — script dibuat dari ide terpilih.</p>}
      {selectedIdeaId && (
        <>
          <button
            type="button"
            className="primary-action"
            disabled={generate.isPending || Boolean(chainActive)}
            onClick={() => generate.mutate()}
          >
            {chainActive
              ? "Rantai script sedang berjalan…"
              : scripts.data && scripts.data.length > 0
                ? "Buat versi script baru"
                : "Buat script dari ide terpilih"}
          </button>
          {generate.isError && (
            <p className="error-text">{(generate.error as Error).message}</p>
          )}
        </>
      )}

      {scripts.data && scripts.data.length > 0 && (
        <div className="version-row">
          {scripts.data.map((script) => (
            <button
              key={script.id}
              type="button"
              className={script.id === detailId ? "tab tab-active" : "tab"}
              onClick={() => setViewedId(script.id)}
            >
              V{script.version} · {script.source} · {scriptStatusLabel(script.status)}
              {script.id === activeScriptId ? " · aktif" : ""}
              {script.best_score !== null ? ` · skor ${script.best_score}` : ""}
            </button>
          ))}
        </div>
      )}

      {data && (
        <>
          <h3>{data.title}</h3>
          <p className="panel-note">
            Hook: “{data.hook}” · Estimasi total {formatDuration(data.estimated_duration_s)} ·
            Status: {scriptStatusLabel(data.status)}
            {data.edited_after_validation ? " · Diedit sesudah divalidasi" : ""}
          </p>
          {!editable && data.id === activeScriptId && chainActive && (
            <p className="panel-note">Editor terkunci selama rantai script berjalan.</p>
          )}
          {!editable && data.id !== activeScriptId && (
            <p className="panel-note">Hanya versi aktif yang bisa diedit.</p>
          )}

          <div className="scene-list">
            {data.scenes.map((scene, index) => (
              <SceneRow
                key={scene.id}
                scene={scene}
                editable={editable}
                isFirst={index === 0}
                isLast={index === data.scenes.length - 1}
                onMove={move}
                showVoice={data.id === activeScriptId}
                voiceBusy={busyVoiceSceneIds.has(scene.id)}
                imageBusy={busyImageSceneIds.has(scene.id)}
              />
            ))}
          </div>

          {editable && (
            <div className="scene-row">
              <strong>Tambah scene di akhir</strong>
              <label>
                Narasi
                <textarea
                  value={newVoiceover}
                  rows={2}
                  onChange={(e) => setNewVoiceover(e.target.value)}
                />
              </label>
              <label>
                Prompt visual (Inggris)
                <input value={newVisual} onChange={(e) => setNewVisual(e.target.value)} />
              </label>
              <button
                type="button"
                disabled={add.isPending || !newVoiceover.trim() || !newVisual.trim()}
                onClick={() => add.mutate()}
              >
                Tambah scene
              </button>
              {add.isError && <p className="error-text">{(add.error as Error).message}</p>}
            </div>
          )}

          <h3>Cek otomatis</h3>
          {data.checks.length === 0 && <p>Tidak ada masalah cek otomatis.</p>}
          {data.checks.length > 0 && (
            <ul className="issue-list">
              {data.checks.map((issue, index) => (
                <li key={index}>
                  <strong>{issue.severity === "error" ? "Kesalahan" : "Peringatan"}:</strong>{" "}
                  {issue.message}
                </li>
              ))}
            </ul>
          )}

          <h3>Validasi</h3>
          {data.validation ? (
            <>
              <p>
                Status: <strong>{data.validation.status}</strong> · Skor{" "}
                {data.validation.score} · {data.validation.summary}
              </p>
              {data.validation.issues.length > 0 && (
                <ul className="issue-list">
                  {data.validation.issues.map((issue, index) => (
                    <li key={index}>
                      <strong>{issue.severity}:</strong> {issue.message}
                      {issue.suggestion ? ` — Saran: ${issue.suggestion}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p>Belum pernah divalidasi.</p>
          )}
          <button
            type="button"
            disabled={revalidate.isPending || Boolean(chainActive)}
            onClick={() => revalidate.mutate()}
          >
            Validasi ulang (manual)
          </button>
          {revalidate.isError && (
            <p className="error-text">{(revalidate.error as Error).message}</p>
          )}

          <h3>Gerbang B — persetujuan</h3>
          {data.claims.length === 0 && <p>Tidak ada klaim yang perlu dicek.</p>}
          {data.claims.length > 0 && (
            <ul className="claims-list">
              {data.claims.map((claim, index) => (
                <li key={index}>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={checkedClaims.has(claim)}
                      onChange={(e) => {
                        const next = new Set(checkedClaims);
                        if (e.target.checked) next.add(claim);
                        else next.delete(claim);
                        setCheckedClaims(next);
                      }}
                    />
                    {claim}
                  </label>
                </li>
              ))}
            </ul>
          )}
          <button
            type="button"
            className="primary-action"
            disabled={!allClaimsChecked || approve.isPending || data.status === "approved"}
            onClick={() => approve.mutate()}
          >
            {data.status === "approved" ? "Script sudah disetujui" : "Setujui script ini"}
          </button>
          {approve.isError && (
            <p className="error-text">{(approve.error as Error).message}</p>
          )}
        </>
      )}
    </section>
  );
}
