"""Pluggable data-vendor adapters. All return the same canonical EOD schema."""
from .base import VendorAdapter, CANONICAL_EOD_COLUMNS, validate_canonical, empty_canonical
from .synthetic import SyntheticEODAdapter
from .nse_bhavcopy import NSEBhavcopyAdapter, parse_udiff_csv, parse_legacy_csv
from .bse_bhavcopy import BSEBhavcopyAdapter, parse_bse_udiff_csv
from .kite import KiteAdapter, KiteHistoricalAdapter, KiteInstruments, KITE_FIELDMAP
from .fieldmap import FieldMap, normalize
from .bar_vendor import BarVendorAdapter
from .dhan_chain import (DhanChainAdapter, DHAN_CHAIN_FIELDMAP, DHAN_UNDERLYING,
                         parse_option_chain, parse_expiry_list, chain_rows_to_records)
from .global_datafeeds import GlobalDatafeedsAdapter, gdfl_symbol, GDFL_FIELDMAP

__all__ = [
    "VendorAdapter", "CANONICAL_EOD_COLUMNS", "validate_canonical", "empty_canonical",
    "SyntheticEODAdapter",
    "NSEBhavcopyAdapter", "parse_udiff_csv", "parse_legacy_csv",
    "BSEBhavcopyAdapter", "parse_bse_udiff_csv",
    "KiteAdapter", "KiteHistoricalAdapter", "KiteInstruments", "KITE_FIELDMAP",
    "FieldMap", "normalize", "BarVendorAdapter",
    "DhanChainAdapter", "DHAN_CHAIN_FIELDMAP", "DHAN_UNDERLYING",
    "parse_option_chain", "parse_expiry_list", "chain_rows_to_records",
    "GlobalDatafeedsAdapter", "gdfl_symbol", "GDFL_FIELDMAP",
]
