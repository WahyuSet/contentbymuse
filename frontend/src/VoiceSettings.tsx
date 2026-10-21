import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { patchProject, type Project } from "./lib/projects";
import { fetchProviderVoices, fetchProviders } from "./lib/voice";

export default function VoiceSettings({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [providerId, setProviderId] = useState(project.voice_provider_id ?? "");
  const [voiceId, setVoiceId] = useState(project.voice_id ?? "");
  const [speed, setSpeed] = useState(
    String((project.voice_settings?.speed as number | undefined) ?? ""),
  );

  useEffect(() => {
    setProviderId(project.voice_provider_id ?? "");
    setVoiceId(project.voice_id ?? "");
    setSpeed(String((project.voice_settings?.speed as number | undefined) ?? ""));
  }, [project.voice_provider_id, project.voice_id, project.voice_settings]);

  const providers = useQuery({ queryKey: ["providers"], queryFn: fetchProviders });
  const voiceProviders = providers.data?.filter(
    (p) => p.capability === "voice" && p.enabled,
  );
  const voices = useQuery({
    queryKey: ["provider-voices", providerId],
    queryFn: () => fetchProviderVoices(providerId),
    enabled: providerId !== "",
  });

  const save = useMutation({
    mutationFn: () =>
      patchProject(project.id, {
        voice_provider_id: providerId === "" ? null : providerId,
        voice_id: voiceId.trim() === "" ? null : voiceId.trim(),
        voice_settings: {
          speed:
            speed.trim() === ""
              ? ((project.voice_settings?.speed as number | undefined) ?? 100)
              : Number(speed),
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", project.id] });
    },
  });

  return (
    <section className="panel">
      <h2>Suara narasi</h2>
      <p className="panel-note">
        Satu suara untuk seluruh project. Kosongkan provider untuk memakai kandidat
        suara teratas; kosongkan suara untuk memakai suara bawaan provider.
      </p>
      <label>
        Provider suara
        <select value={providerId} onChange={(e) => setProviderId(e.target.value)}>
          <option value="">Otomatis (kandidat teratas)</option>
          {voiceProviders?.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Suara
        <input
          value={voiceId}
          list="voice-options"
          placeholder="bawaan provider"
          onChange={(e) => setVoiceId(e.target.value)}
        />
        <datalist id="voice-options">
          {voices.data?.map((voice) => (
            <option key={voice.id} value={voice.id}>
              {voice.name}
            </option>
          ))}
        </datalist>
      </label>
      <label>
        Kecepatan (persen, untuk provider yang mendukung)
        <input
          value={speed}
          inputMode="numeric"
          placeholder="100"
          onChange={(e) => setSpeed(e.target.value)}
        />
      </label>
      <button
        type="button"
        className="primary-action"
        disabled={save.isPending}
        onClick={() => save.mutate()}
      >
        {save.isPending ? "Menyimpan…" : "Simpan pengaturan suara"}
      </button>
      {save.isError && <p className="error-text">{(save.error as Error).message}</p>}
      {save.isSuccess && <p className="panel-note">Pengaturan suara tersimpan.</p>}
    </section>
  );
}
