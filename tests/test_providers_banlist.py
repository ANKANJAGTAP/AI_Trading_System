"""NSE F&O ban-list parsing + provider caching (pure / injected fetcher)."""
import asyncio

from strategies.providers import NSEBanListProvider, parse_secban


def test_parse_secban_rows_and_header():
    txt = "Securities in Ban for 27-JUN-2026\n1,ABFRL\n2,BANDHANBNK\n3, HINDCOPPER \n"
    assert parse_secban(txt) == {"ABFRL", "BANDHANBNK", "HINDCOPPER"}
    assert parse_secban("") == set()
    assert parse_secban("no,digit\nheader,row") == set()   # non-numeric first field -> skipped


def test_provider_uses_fetcher_caches_and_indices_never_banned():
    calls = {"n": 0}

    async def fake():
        calls["n"] += 1
        return "1,ABFRL\n2,IDEA\n"

    p = NSEBanListProvider(fetcher=fake)

    async def run():
        assert await p.is_banned("IDEA") is True
        assert await p.is_banned("idea") is True          # case-insensitive
        assert await p.is_banned("NIFTY") is False         # index never on the list
        return calls["n"]

    assert asyncio.run(run()) == 1   # fetched once, cached for the trading day
