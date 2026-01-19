"""
S&P 500 companies list with sector classification.
This list is updated as of January 2025.
Note: The actual list changes periodically. Consider fetching dynamically from FMP API.
"""

from typing import Dict, List

# S&P 500 tickers organized by GICS sector
SP500_BY_SECTOR: Dict[str, List[str]] = {
    "Information Technology": [
        "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "CSCO", "AMD", "ACN", "ADBE",
        "IBM", "TXN", "QCOM", "INTU", "AMAT", "NOW", "PANW", "ADI", "LRCX", "MU",
        "KLAC", "SNPS", "CDNS", "MCHP", "APH", "MSI", "ROP", "FTNT", "NXPI", "HPQ",
        "DELL", "ON", "ANSS", "TEL", "KEYS", "MPWR", "FSLR", "CDW", "TYL", "ZBRA",
        "FICO", "IT", "TDY", "STX", "NTAP", "JNPR", "WDC", "SWKS", "AKAM", "PTC",
        "GEN", "EPAM", "TRMB", "CTSH", "HPE", "FFIV", "QRVO", "ENPH", "SEDG",
    ],
    "Health Care": [
        "LLY", "UNH", "JNJ", "MRK", "ABBV", "TMO", "ABT", "DHR", "PFE", "AMGN",
        "ISRG", "ELV", "SYK", "GILD", "MDT", "BMY", "VRTX", "BSX", "CI", "CVS",
        "REGN", "ZTS", "BDX", "HCA", "MCK", "HUM", "EW", "IDXX", "IQV", "DXCM",
        "A", "CNC", "RMD", "MTD", "BIIB", "ZBH", "LH", "MRNA", "BAX", "CAH",
        "COO", "WAT", "WST", "ALGN", "HOLX", "MOH", "CRL", "VTRS", "DGX", "TECH",
        "HSIC", "CTLT", "XRAY", "INCY", "BIO", "TFX", "OGN", "DVA",
    ],
    "Financials": [
        "BRK.B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "AXP",
        "BLK", "SCHW", "C", "CB", "PGR", "MMC", "ICE", "CME", "AON", "MCO",
        "USB", "PNC", "TFC", "AIG", "MET", "AFL", "AMP", "MSCI", "PRU", "TRV",
        "ALL", "BK", "COF", "FITB", "HIG", "NDAQ", "MTB", "DFS", "STT", "RJF",
        "HBAN", "TROW", "NTRS", "CINF", "RF", "CFG", "KEY", "FDS", "EG", "WRB",
        "L", "BRO", "CBOE", "JKHY", "MKTX", "GL", "AIZ", "RE", "IVZ", "BEN",
        "ZION", "LNC",
    ],
    "Consumer Discretionary": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG",
        "ORLY", "MAR", "AZO", "GM", "F", "ROST", "HLT", "DHI", "YUM", "LULU",
        "LEN", "DG", "DLTR", "EBAY", "NVR", "PHM", "ULTA", "TSCO", "BBY", "DECK",
        "GPC", "APTV", "POOL", "GRMN", "DRI", "CCL", "LKQ", "RCL", "MGM", "WYNN",
        "CZR", "BWA", "TPR", "HAS", "KMX", "NCLH", "MHK", "WHR", "AAP", "PVH",
        "RL", "NWL", "VFC",
    ],
    "Communication Services": [
        "META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS", "CHTR",
        "EA", "TTWO", "WBD", "OMC", "LYV", "IPG", "MTCH", "PARA", "FOXA", "FOX",
        "NWS", "NWSA",
    ],
    "Industrials": [
        "GE", "CAT", "RTX", "HON", "UNP", "UPS", "DE", "BA", "LMT", "ADP",
        "ETN", "TT", "GD", "NOC", "ITW", "WM", "EMR", "FDX", "CSX", "NSC",
        "PH", "PCAR", "JCI", "CTAS", "GWW", "CARR", "OTIS", "CPRT", "FAST", "CMI",
        "AME", "VRSK", "RSG", "ODFL", "LHX", "PWR", "IR", "ROK", "PAYX", "EFX",
        "DOV", "HWM", "HUBB", "XYL", "WAB", "TXT", "FTV", "BR", "SNA", "LDOS",
        "J", "IEX", "PNR", "CHRW", "JBHT", "EXPD", "ALLE", "MAS", "NDSN", "AOS",
        "GNRC", "RHI", "PAYC", "DAY", "SWK", "ALLE",
    ],
    "Consumer Staples": [
        "PG", "COST", "WMT", "KO", "PEP", "PM", "MO", "MDLZ", "CL", "KMB",
        "GIS", "EL", "ADM", "SYY", "STZ", "HSY", "KHC", "K", "MNST", "KDP",
        "CHD", "MKC", "CLX", "SJM", "TSN", "HRL", "CAG", "TAP", "CPB", "LW",
        "BG", "BF.B",
    ],
    "Energy": [
        "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "PXD", "VLO", "WMB",
        "OKE", "HES", "KMI", "BKR", "HAL", "OXY", "FANG", "DVN", "TRGP", "CTRA",
        "MRO", "APA",
    ],
    "Utilities": [
        "NEE", "SO", "DUK", "CEG", "SRE", "AEP", "D", "EXC", "XEL", "PCG",
        "ED", "PEG", "WEC", "EIX", "AWK", "DTE", "ETR", "PPL", "ES", "FE",
        "AEE", "CMS", "CNP", "ATO", "EVRG", "NI", "LNT", "NRG", "PNW",
    ],
    "Real Estate": [
        "PLD", "AMT", "EQIX", "WELL", "SPG", "PSA", "DLR", "O", "CCI", "VICI",
        "AVB", "SBAC", "CBRE", "WY", "EQR", "EXR", "ARE", "VTR", "MAA", "IRM",
        "INVH", "ESS", "KIM", "UDR", "HST", "REG", "CPT", "BXP", "DOC", "FRT",
    ],
    "Materials": [
        "LIN", "APD", "SHW", "FCX", "ECL", "NEM", "NUE", "CTVA", "DOW", "DD",
        "VMC", "PPG", "MLM", "IFF", "ALB", "LYB", "FMC", "CE", "CF", "MOS",
        "PKG", "AVY", "IP", "EMN", "BALL", "WRK", "SEE", "AMCR",
    ],
}

# Flat list of all S&P 500 tickers
SP500_TICKERS: List[str] = [
    ticker for sector_tickers in SP500_BY_SECTOR.values() for ticker in sector_tickers
]


def get_sp500_by_sector(sector: str) -> List[str]:
    """Get list of tickers for a specific sector."""
    return SP500_BY_SECTOR.get(sector, [])


def get_all_sectors() -> List[str]:
    """Get list of all GICS sectors."""
    return list(SP500_BY_SECTOR.keys())


def get_sector_for_ticker(ticker: str) -> str:
    """Get the sector for a specific ticker."""
    for sector, tickers in SP500_BY_SECTOR.items():
        if ticker in tickers:
            return sector
    return "Unknown"


async def fetch_current_sp500_list(fmp_client) -> List[str]:
    """
    Fetch the current S&P 500 constituent list from FMP API.
    This ensures we have the most up-to-date list.
    """
    try:
        constituents = await fmp_client.get_sp500_constituents()
        return [c["symbol"] for c in constituents]
    except Exception:
        # Fall back to static list if API fails
        return SP500_TICKERS
