import hashlib

from app.audit.service import compute_hash


def test_compute_hash_deterministic():
    h1 = compute_hash("prev", "2026-01-01T00:00:00", 1, "create", "{}")
    h2 = compute_hash("prev", "2026-01-01T00:00:00", 1, "create", "{}")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_compute_hash_changes_with_payload():
    h1 = compute_hash(None, "t", 1, "create", "a")
    h2 = compute_hash(None, "t", 1, "create", "b")
    assert h1 != h2


def test_compute_hash_chains():
    h1 = compute_hash(None, "t1", 1, "action1", "{}")
    h2 = compute_hash(h1, "t2", 2, "action2", "{}")
    h3 = compute_hash(h2, "t3", 3, "action3", "{}")
    assert h2 != h1 and h3 != h2
    # hash = sha256(prev_hash || timestamp || actor_id || action || payload)
    assert hashlib.sha256(f"{h1}t22action2{{}}".encode()).hexdigest() == h2
    assert hashlib.sha256(f"{h2}t33action3{{}}".encode()).hexdigest() == h3
