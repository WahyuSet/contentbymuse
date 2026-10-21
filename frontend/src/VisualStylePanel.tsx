import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchVisualStyles,
  patchVisualStyle,
  type VisualStyle,
} from "./lib/images";
import { patchProject, type Project } from "./lib/projects";
import { fetchProviders } from "./lib/voice";

export default function VisualStylePanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: fetchProviders,
  });
  const styles = useQuery({
    queryKey: ["visual-styles"],
    queryFn: fetchVisualStyles,
  });
  const imageProviders = (providers.data ?? []).filter(
    (p) => p.capability === "image" && p.enabled,
  );
  const styleList = styles.data ?? [];
  const effectiveStyleId =
    project.visual_style_id ??
    styleList.find((s) => s.is_default)?.id ??
    styleList[0]?.id ??
    "";
  const [editId, setEditId] = useState<string>("");
  const editStyle: VisualStyle | undefined =
    styleList.find((s) => s.id === (editId || effectiveStyleId)) ??
    styleList[0];
  const [styleText, setStyleText] = useState("");
  const [negativeText, setNegativeText] = useState("");
  const [mascotAnchor, setMascotAnchor] = useState("");
  useEffect(() => {
    if (editStyle) {
      setStyleText(editStyle.style_text);
      setNegativeText(editStyle.negative_text);
      setMascotAnchor(editStyle.mascot_anchor);
    }
  }, [editStyle?.id, editStyle?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const savePin = useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      patchProject(project.id, patch),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project", project.id] }),
  });
  const saveStyle = useMutation({
    mutationFn: () =>
      patchVisualStyle(editStyle!.id, {
        style_text: styleText,
        negative_text: negativeText,
        mascot_anchor: mascotAnchor,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["visual-styles"] }),
  });

  return (
    <section className="panel">
      <h2>Gambar</h2>
      <div className="voice-grid">
        <label>
          Provider gambar
          <select
            value={project.image_provider_id ?? ""}
            onChange={(e) =>
              savePin.mutate({
                image_provider_id: e.target.value || null,
              })
            }
          >
            <option value="">Otomatis (prioritas router)</option>
            {imageProviders.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Gaya visual project
          <select
            value={project.visual_style_id ?? ""}
            onChange={(e) =>
              savePin.mutate({ visual_style_id: e.target.value || null })
            }
          >
            <option value="">Gaya bawaan</option>
            {styleList.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
                {s.is_default ? " (bawaan)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Gaya yang diedit
          <select
            value={editStyle?.id ?? ""}
            onChange={(e) => setEditId(e.target.value)}
          >
            {styleList.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · versi {s.version}
              </option>
            ))}
          </select>
        </label>
      </div>
      {editStyle && (
        <>
          <label>
            Teks gaya (masuk prompt gambar)
            <textarea
              value={styleText}
              rows={3}
              onChange={(e) => setStyleText(e.target.value)}
            />
          </label>
          <label>
            Jangkar maskot
            <textarea
              value={mascotAnchor}
              rows={2}
              onChange={(e) => setMascotAnchor(e.target.value)}
            />
          </label>
          <label>
            Teks negatif
            <textarea
              value={negativeText}
              rows={2}
              onChange={(e) => setNegativeText(e.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={() => saveStyle.mutate()}
            disabled={saveStyle.isPending}
          >
            Simpan gaya
          </button>
          {saveStyle.isSuccess && (
            <p className="panel-note">
              Gaya tersimpan sebagai versi {editStyle.version}. Gambar yang
              sudah jadi tidak berubah; buat ulang gambar untuk memakai gaya
              baru.
            </p>
          )}
        </>
      )}
    </section>
  );
}
