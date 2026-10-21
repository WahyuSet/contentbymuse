import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Project, Script

logger = logging.getLogger(__name__)


async def reconcile(project_id: str | None, factory: async_sessionmaker | None = None) -> None:
    """Menghubungkan keadaan project ke job berikutnya (Spec §4.12).

    Gerbang A: ide terpilih yang belum punya script mengantrekan job script.
    Cabang produksi sesudah Gerbang B diisi Fase 4-6.
    """
    if project_id is None or factory is None:
        return
    from app.db.models import GenerationJob
    from app.jobs.handlers import HANDLERS
    from app.jobs.queue import enqueue_once

    if "script" not in HANDLERS:
        return
    async with factory() as session:
        project = await session.get(Project, project_id)
        if project is None or project.selected_idea_id is None:
            return
        existing = (
            await session.execute(
                select(Script.id).where(Script.idea_id == project.selected_idea_id)
            )
        ).first()
        if existing is not None:
            if project.active_script_id is None:
                # Rantai bisa berhenti tanpa keputusan (job gagal final/dibatalkan):
                # tetapkan versi terbaik yang ada sebagai aktif (Spec §4.4/§4.12).
                active_jobs = (
                    await session.execute(
                        select(GenerationJob.id).where(
                            GenerationJob.project_id == project.id,
                            GenerationJob.type.in_(
                                ("script", "checks_fix", "validate", "revise")
                            ),
                            GenerationJob.status.in_(("queued", "processing")),
                        )
                    )
                ).first()
                if active_jobs is None:
                    from app.services.finalize import finalize_best

                    await finalize_best(session, project)
                    await session.commit()
            return
        _job, created = await enqueue_once(
            session,
            type="script",
            input={"idea_id": project.selected_idea_id},
            project_id=project.id,
        )
        await session.commit()
        if created:
            logger.info("reconcile: job script diantrekan untuk project %s", project_id)
