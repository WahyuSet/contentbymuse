import time

from app.ids import new_ulid

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_ulid_is_26_crockford_chars():
    value = new_ulid()
    assert len(value) == 26
    assert set(value) <= CROCKFORD


def test_ulid_calls_differ():
    assert new_ulid() != new_ulid()


def test_ulid_sorts_by_time():
    older = new_ulid(int(time.time() * 1000) - 5000)
    newer = new_ulid(int(time.time() * 1000))
    assert older < newer
