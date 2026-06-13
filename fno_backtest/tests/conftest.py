import pandas as pd
import pytest

from dataplatform.vendors import SyntheticEODAdapter


@pytest.fixture(scope="module")
def eod():
    ad = SyntheticEODAdapter()
    days = pd.bdate_range("2026-03-02", "2026-05-29")
    return pd.concat([ad.fetch_eod_fno(d.date()) for d in days], ignore_index=True)
