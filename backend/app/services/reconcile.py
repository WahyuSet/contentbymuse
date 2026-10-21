import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Project

logger = logging.getLogger(__name__)


async def reconcile(project_id: str | None, factory: async_sessionmaker | None = None) -> None:
    """Menghubungkan keadaan project ke job berikutnya (Spec §4.12).

    Fase 2 baru mengisi cabang Gerbang A: ide terpilih tanpa script meng-enqueue
    job script — aktif hanya bila handler script sudah terdaftar (Fase 3).
    Tahap produksi sesudah Gerbang B diisi Fase 4-6.
    """
    if project_id is None or factory is None:
        return
    from app.jobs.handlers import HANDLERS
    from app.jobs.queue import enqueue

    if "script" not in HANDLERS:
        return
    async with factory() as session:
        project = await session.get(Project, project_id)
        if project is None or project.selected_idea_id is None:
            return
        await enqueue(
            session,
            type="script",
            input={"idea_id": project.selected_idea_id},
            project_id=project.id,
        )
        await session.commit()
        logger.info("reconcile: job script diantrekan untuk project %s", project_id)
