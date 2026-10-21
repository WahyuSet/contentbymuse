import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createProject,
  fetchCategories,
  fetchFormats,
  fetchProjects,
} from "./lib/projects";

export default function ProjectsPage({
  onOpen,
}: {
  onOpen: (projectId: string) => void;
}) {
  const [topic, setTopic] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [formatId, setFormatId] = useState("");
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: fetchProjects });
  const categories = useQuery({ queryKey: ["categories"], queryFn: fetchCategories });
  const formats = useQuery({ queryKey: ["formats"], queryFn: fetchFormats });

  const create = useMutation({
    mutationFn: () =>
      createProject({
        topic: topic.trim() || undefined,
        category_id: categoryId || undefined,
        format_id: formatId || undefined,
      }),
    onSuccess: (project) => {
      setTopic("");
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      onOpen(project.id);
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  const categoryName = (id: string | null) =>
    categories.data?.find((c) => c.id === id)?.name ?? null;

  return (
    <>
      <section className="panel">
        <h2>Project baru</h2>
        <p className="panel-note">
          Isi topik, atau pilih kategori saja dan biarkan sistem menemukan ide di
          dalamnya. Format boleh kosong (bebas).
        </p>
        <form onSubmit={onSubmit} className="project-form">
          <input
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="Topik, mis. kenapa cicak bisa menempel di dinding"
            aria-label="Topik"
          />
          <select
            value={categoryId}
            onChange={(event) => setCategoryId(event.target.value)}
            aria-label="Kategori"
          >
            <option value="">Kategori: tebak dari topik</option>
            {categories.data?.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
                {category.fact_check === "strict" ? " (cek fakta ketat)" : ""}
              </option>
            ))}
          </select>
          <select
            value={formatId}
            onChange={(event) => setFormatId(event.target.value)}
            aria-label="Format"
          >
            <option value="">Format: bebas</option>
            {formats.data?.map((format) => (
              <option key={format.id} value={format.id}>
                {format.name}
              </option>
            ))}
          </select>
          <button type="submit" disabled={create.isPending}>
            {create.isPending ? "Membuat…" : "Buat project"}
          </button>
        </form>
        {create.isError && (
          <p className="error-text">{(create.error as Error).message}</p>
        )}
      </section>

      <section className="panel">
        <h2>Daftar project</h2>
        {projects.isPending && <p>Memuat…</p>}
        {projects.isError && (
          <p className="error-text">
            API tidak terjangkau. Pastikan backend jalan di 127.0.0.1:8010.
          </p>
        )}
        {projects.data && projects.data.length === 0 && (
          <p>Belum ada project. Buat project pertama di atas.</p>
        )}
        {projects.data && projects.data.length > 0 && (
          <ul className="project-list">
            {projects.data.map((project) => (
              <li key={project.id}>
                <button
                  type="button"
                  className="project-row"
                  onClick={() => onOpen(project.id)}
                >
                  <span className="project-title">{project.title}</span>
                  <span className="project-meta">
                    {project.topic ? `Topik: ${project.topic} · ` : ""}
                    {categoryName(project.category_id)
                      ? `Kategori: ${categoryName(project.category_id)} · `
                      : ""}
                    {project.idea_count} ide
                    {project.selected_idea_id ? " · ide sudah dipilih" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
