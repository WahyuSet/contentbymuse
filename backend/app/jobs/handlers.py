import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import UsageRecord
from app.jobs.context import DbCallContext, JobCancelled
from app.providers.base import Message, TextRequest
from app.providers.registry import ADAPTERS


async def run_provider_test(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    await ctx.log("info", "Tes provider fake dimulai")
    await ctx.progress(50, "Memanggil provider fake")
    label = str(job.input.get("label", ""))
    llm = ADAPTERS[("llm", "fake")]()
    result = await llm.generate_text(
        TextRequest(messages=[Message(role="user", content=label)]), ctx
    )
    sleep_ms = min(int(job.input.get("sleep_ms", 0)), 2000)
    if sleep_ms:
        await asyncio.sleep(sleep_ms / 1000)
    if await ctx.cancelled():
        raise JobCancelled()
    async with factory() as session:
        session.add(
            UsageRecord(
                job_id=job.id,
                project_id=job.project_id,
                model=result.model,
                capability="llm",
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                succeeded=True,
            )
        )
        await session.commit()
    await ctx.progress(100, "Selesai")
    try:
        parsed = json.loads(result.text)
    except json.JSONDecodeError:
        parsed = {"text": result.text}
    return {"llm": parsed, "label": label}


from app.jobs.align import run_align
from app.jobs.checks_fix import run_checks_fix
from app.jobs.ideas import run_ideas
from app.jobs.revise import run_revise
from app.jobs.script import run_script
from app.jobs.validate import run_validate
from app.jobs.voice import run_voice

HANDLERS = {
    "provider_test": run_provider_test,
    "ideas": run_ideas,
    "script": run_script,
    "checks_fix": run_checks_fix,
    "validate": run_validate,
    "revise": run_revise,
    "voice": run_voice,
    "align": run_align,
}
