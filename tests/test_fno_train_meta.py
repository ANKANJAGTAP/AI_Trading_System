"""fno_train_meta pure helpers (no lake/engine — heavy imports live inside _run)."""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "fno_train_meta.py")
_spec = importlib.util.spec_from_file_location("fno_train_meta", _PATH)
ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ft)


def test_cv_index_splits_expanding_and_purged():
    splits = ft.cv_index_splits(60, folds=5, embargo=1)
    assert len(splits) == 5
    # fold 1: train ends embargo before the test block; test is the next segment
    tr, te = splits[0]
    assert (tr.start, tr.stop) == (0, 9) and (te.start, te.stop) == (10, 20)
    # last fold's test runs to n
    tr5, te5 = splits[4]
    assert (te5.start, te5.stop) == (50, 60)
    assert tr5.stop == 49                     # expanding window grows
    assert ft.cv_index_splits(3, folds=5, embargo=1) == []   # too small


def test_build_samples_from_trades_joins_and_labels():
    captured = {"2024-07-25": {"rsi_14": 60.0, "dte": 3.0},
                "2024-08-01 00:00:00": {"rsi_14": 40.0, "dte": 5.0}}
    records = [{"entry_date": "2024-07-25 00:00:00", "net": 1500.0},
               {"entry_date": "2024-08-01", "net": -200.0},
               {"entry_date": "2024-09-01", "net": 10.0}]   # no captured features -> skipped
    samples = ft.build_samples_from_trades(captured, records)
    assert len(samples) == 2
    assert samples[0] == {"features": {"rsi_14": 60.0, "dte": 3.0}, "label": 1}   # net>0 -> win
    assert samples[1]["label"] == 0                                              # net<0 -> loss


def test_num_handles_nan_and_junk():
    assert ft._num(3.5) == 3.5
    assert ft._num(float("nan")) == 0.0
    assert ft._num(None) == 0.0 and ft._num("x") == 0.0
