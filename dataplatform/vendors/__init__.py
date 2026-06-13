"""Pluggable data-vendor adapters. All return the same canonical EOD schema."""
from .base import VendorAdapter, CANONICAL_EOD_COLUMNS, validate_canonical, empty_canonical
from .synthetic import SyntheticEODAdapter
from .nse_bhavcopy import NSEBhavcopyAdapter, parse_udiff_csv, parse_legacy_csv
from .bse_bhavcopy import BSEBhavcopyAdapter, parse_bse_udiff_csv
from .kite import KiteAdapter
from .fieldmap import FieldMap, normalize
from .bar_vendor import BarVendorAdapter
from .truedata import TrueDataAdapter, truedata_symbol, TRUEDATA_FIELDMAP
from .global_datafeeds import GlobalDatafeedsAdapter, gdfl_symbol, GDFL_FIELDMAP

__all__ = [
    "VendorAdapter", "CANONICAL_EOD_COLUMNS", "validate_canonical", "empty_canonical",
    "SyntheticEODAdapter",
    "NSEBhavcopyAdapter", "parse_udiff_csv", "parse_legacy_csv",
    "BSEBhavcopyAdapter", "parse_bse_udiff_csv",
    "KiteAdapter",
    "FieldMap", "normalize", "BarVendorAdapter",
    "TrueDataAdapter", "truedata_symbol", "TRUEDATA_FIELDMAP",
    "GlobalDatafeedsAdapter", "gdfl_symbol", "GDFL_FIELDMAP",
]
