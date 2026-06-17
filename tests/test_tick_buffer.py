"""#28 — bounded coalescing tick buffer (pure)."""
from common.tick_buffer import CoalescingTickBuffer


def test_latest_wins_and_coalesces():
    b = CoalescingTickBuffer()
    b.put("NIFTY", 100)
    b.put("NIFTY", 101)
    b.put("NIFTY", 102)        # two supersedes
    assert len(b) == 1
    assert b.coalesced == 2
    assert b.drain() == {"NIFTY": 102}


def test_drain_clears():
    b = CoalescingTickBuffer()
    b.put("A", 1)
    b.put("B", 2)
    assert b.drain() == {"A": 1, "B": 2}
    assert len(b) == 0
    assert b.drain() == {}


def test_bounded_eviction_of_oldest_symbol():
    b = CoalescingTickBuffer(max_symbols=2)
    b.put("A", 1)
    b.put("B", 2)
    b.put("C", 3)              # evicts oldest symbol "A"
    assert len(b) == 2
    assert b.evicted == 1
    snap = b.drain()
    assert "A" not in snap and snap == {"B": 2, "C": 3}


def test_updating_existing_symbol_does_not_evict():
    b = CoalescingTickBuffer(max_symbols=2)
    b.put("A", 1)
    b.put("B", 2)
    b.put("A", 9)              # update, not a new slot
    assert b.evicted == 0
    assert b.drain() == {"A": 9, "B": 2}
