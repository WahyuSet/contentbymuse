from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import utcnow
from app.jobs.queue import claim_next, enqueue


async def test_claim_takes_lowest_priority_then_fifo(session):
    await enqueue(session, type="provider_test", input={"n": 1}, priority=200)
    first = await enqueue(session, type="provider_test", input={"n": 2}, priority=50)
    second = await enqueue(session, type="provider_test", input={"n": 3}, priority=50)
    await session.commit()

    claimed = await claim_next(session, worker_id="w1")
    assert claimed.id == first.id
    claimed = await claim_next(session, worker_id="w1")
    assert claimed.id == second.id


async def test_claim_skips_future_and_full_resource(session):
    await enqueue(session, type="provider_test", input={"n": 1}, resource_key="render")
    await session.commit()
    assert await claim_next(session, worker_id="w1", full_keys={"render"}) is None

    job = await enqueue(session, type="provider_test", input={"n": 2})
    job.run_after = utcnow() + timedelta(minutes=5)
    await session.commit()
    assert await claim_next(session, worker_id="w1", full_keys={"render"}) is None


async def test_duplicate_active_job_hits_unique_index(session):
    await enqueue(session, type="provider_test", input={"same": True})
    await session.commit()
    with pytest.raises(IntegrityError):
        await enqueue(session, type="provider_test", input={"same": True})
        await session.commit()
