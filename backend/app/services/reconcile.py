import logging

logger = logging.getLogger(__name__)


async def reconcile(project_id: str | None) -> None:
    """Kerangka Fase 1: rantai produksi diisi mulai Fase 2 (Spec §4.12)."""
    logger.info("reconcile dipanggil untuk project=%s (kerangka, tanpa aksi)", project_id)
