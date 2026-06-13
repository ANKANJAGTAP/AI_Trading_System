"""Parser tests use small inline CSV fixtures — no network required."""
import datetime as dt

from dataplatform.vendors import parse_udiff_csv, parse_legacy_csv, parse_bse_udiff_csv
from dataplatform.vendors.base import CANONICAL_EOD_COLUMNS

# --- NSE UDiFF fixture: 1 index future, 1 index option, 1 stock option (dropped) ---
UDIFF = (
    "TradDt,TckrSymb,FinInstrmTp,OptnTp,XpryDt,StrkPric,"
    "OpnPric,HghPric,LwPric,ClsPric,SttlmPric,TtlTradgVol,OpnIntrst,ChngInOpnIntrst\n"
    "2024-07-25,NIFTY,IDF,,2024-07-25,0,24000,24100,23950,24050,24050,1000,500000,1200\n"
    "2024-07-25,NIFTY,IDO,CE,2024-07-25,24000,150,180,140,160,160,5000,300000,-400\n"
    "2024-07-25,RELIANCE,STO,PE,2024-07-25,2900,30,35,28,33,33,200,10000,50\n"
)

# --- legacy NSE F&O bhavcopy fixture (note trailing comma -> Unnamed col) ---
LEGACY = (
    "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,"
    "SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,\n"
    "FUTIDX,NIFTY,25-JUL-2024,0,XX,24000,24100,23950,24050,24050,1000,2400,500000,1200,01-JUL-2024,\n"
    "OPTIDX,NIFTY,25-JUL-2024,24000,CE,150,180,140,160,160,5000,80,300000,-400,01-JUL-2024,\n"
    "FUTSTK,RELIANCE,25-JUL-2024,0,XX,2900,2950,2880,2930,2930,300,900,12000,100,01-JUL-2024,\n"
)

# --- BSE UDiFF fixture: SENSEX future + option ---
BSE = (
    "TradDt,TckrSymb,FinInstrmTp,OptnTp,XpryDt,StrkPric,"
    "OpnPric,HghPric,LwPric,ClsPric,SttlmPric,TtlTradgVol,OpnIntrst,ChngInOpnIntrst\n"
    "2024-07-26,SENSEX,IDF,,2024-07-26,80000,80100,79900,80050,80050,800,90000,300\n"
    "2024-07-26,SENSEX,IDO,PE,2024-07-26,80000,200,250,180,220,220,1500,40000,120\n"
)


def test_parse_udiff_schema_and_mapping():
    df = parse_udiff_csv(UDIFF)
    assert list(df.columns) == CANONICAL_EOD_COLUMNS
    assert len(df) == 2  # stock option dropped
    assert set(df["underlying"]) == {"NIFTY"}
    fut = df[df["instrument"] == "FUT"].iloc[0]
    assert fut["opt_type"] == "" and fut["exchange"] == "NSE"
    opt = df[df["instrument"] == "OPT"].iloc[0]
    assert opt["opt_type"] == "CE" and opt["strike"] == 24000
    assert opt["trade_date"] == dt.date(2024, 7, 25)
    assert opt["expiry"] == dt.date(2024, 7, 25)


def test_parse_legacy_schema_and_mapping():
    df = parse_legacy_csv(LEGACY)
    assert list(df.columns) == CANONICAL_EOD_COLUMNS
    assert len(df) == 2  # FUTSTK dropped
    fut = df[df["instrument"] == "FUT"].iloc[0]
    assert fut["opt_type"] == ""           # 'XX' normalised to ''
    assert fut["trade_date"] == dt.date(2024, 7, 1)
    assert fut["expiry"] == dt.date(2024, 7, 25)
    opt = df[df["instrument"] == "OPT"].iloc[0]
    assert opt["opt_type"] == "CE" and opt["oi"] == 300000


def test_parse_bse_udiff():
    df = parse_bse_udiff_csv(BSE)
    assert list(df.columns) == CANONICAL_EOD_COLUMNS
    assert set(df["exchange"]) == {"BSE"}
    assert set(df["underlying"]) == {"SENSEX"}
    assert len(df) == 2
