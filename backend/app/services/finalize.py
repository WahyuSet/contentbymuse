from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Script, ValidationResult
from app.jobs.script_chain import checks_for


async def _latest_validation(session: AsyncSession, script_id: str) -> ValidationResult | None:
    stmt = (
        select(ValidationResult)
        .where(ValidationResult.script_id == script_id)
        .order_by(ValidationResult.attempt.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def finalize_best(session: AsyncSession, project: Project) -> Script | None:
    """Memilih versi script terbaik sebagai aktif (Spec §4.4).

    Urutan: tanpa error cek otomatis -> validasi terakhir tanpa issue error ->
    best_score tertinggi -> versi terbaru.
    """
    stmt = select(Script).where(Script.project_id == project.id)
    if project.selected_idea_id:
        stmt = stmt.where(Script.idea_id == project.selected_idea_id)
    scripts = list((await session.execute(stmt)).scalars())
    if not scripts:
        return None

    async def rank(script: Script) -> tuple:
        issues = await checks_for(session, project, script)
        has_check_errors = any(i.severity == "error" for i in issues)
        latest = await _latest_validation(session, script.id)
        validation_bad = latest is None or any(
            issue.get("severity") == "error" for issue in (latest.issues or [])
        )
        return (
            has_check_errors,
            validation_bad,
            -(script.best_score or 0),
            -script.version,
        )

    ranked = [(await rank(script), script) for script in scripts]
    ranked.sort(key=lambda pair: pair[0])
    best = ranked[0][1]
    project.active_script_id = best.id
    await session.flush()
    return best
