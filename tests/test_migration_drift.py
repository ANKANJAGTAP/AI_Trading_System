"""#16 — migration drift detection (pure). A migration is 'drifted' when its
on-disk checksum no longer matches what was recorded at apply time."""
from migrations.runner import detect_drift


def test_no_drift_when_checksums_match():
    stored = {"0001": "aaa", "0002": "bbb"}
    current = {"0001": "aaa", "0002": "bbb", "0003": "ccc"}  # 0003 pending, not drift
    assert detect_drift(stored, current) == []


def test_drift_when_a_file_changed():
    stored = {"0001": "aaa", "0002": "bbb"}
    current = {"0001": "aaa", "0002": "CHANGED"}
    assert detect_drift(stored, current) == ["0002"]


def test_null_stored_checksum_is_skipped():
    # legacy rows without a recorded checksum can't be compared
    stored = {"0001": None}
    current = {"0001": "aaa"}
    assert detect_drift(stored, current) == []


def test_missing_file_is_not_reported_as_drift():
    # a recorded migration whose file is absent isn't a checksum drift
    stored = {"0001": "aaa", "0099": "zzz"}
    current = {"0001": "aaa"}
    assert detect_drift(stored, current) == []


def test_multiple_drift_sorted():
    stored = {"0002": "b", "0001": "a"}
    current = {"0001": "X", "0002": "Y"}
    assert detect_drift(stored, current) == ["0001", "0002"]
