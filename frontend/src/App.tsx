import { useState } from "react";

import JobsPage from "./JobsPage";
import ProjectDetail from "./ProjectDetail";
import ProjectsPage from "./ProjectsPage";

type View =
  | { name: "projects" }
  | { name: "project"; id: string }
  | { name: "jobs" };

export default function App() {
  const [view, setView] = useState<View>({ name: "projects" });

  return (
    <div className="page">
      <header className="masthead">
        <span className="mascot-head" aria-hidden="true" />
        <div>
          <h1>Stickman Content Factory</h1>
          <p>Antrean produksi @TikusBerdasi — Fase 2: project dan ide.</p>
        </div>
      </header>

      <nav className="tabs" aria-label="Tampilan utama">
        <button
          type="button"
          className={view.name !== "jobs" ? "tab tab-active" : "tab"}
          onClick={() => setView({ name: "projects" })}
        >
          Proyek
        </button>
        <button
          type="button"
          className={view.name === "jobs" ? "tab tab-active" : "tab"}
          onClick={() => setView({ name: "jobs" })}
        >
          Antrean Job
        </button>
      </nav>

      {view.name === "projects" && (
        <ProjectsPage onOpen={(id) => setView({ name: "project", id })} />
      )}
      {view.name === "project" && (
        <ProjectDetail
          projectId={view.id}
          onBack={() => setView({ name: "projects" })}
        />
      )}
      {view.name === "jobs" && <JobsPage />}
    </div>
  );
}
