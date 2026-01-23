"""
Portfolio History Calculator
Builds accurate historical portfolio values using transaction data and market prices.

This is a SEPARATE step from TR sync - called explicitly via "Recalculate History" button.
"""

import json
import re
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd
import yfinance as yf
import logging

log = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path.home() / ".pytr"
PRICE_CACHE_FILE = CACHE_DIR / "price_cache.json"  # {isin: {date: price}}
PORTFOLIO_HISTORY_CACHE_FILE = CACHE_DIR / "portfolio_history_cache.json"
ISIN_SYMBOL_CACHE_FILE = CACHE_DIR / "isin_symbol_cache.json"

# ============================================================================
# TICKER MAPPINGS - See docs/portfolio_valuation.md for full documentation
# ============================================================================

# US stocks MUST use explicit tickers (Yahoo cannot look up US ISINs)
# All US stocks return USD prices - must convert to EUR
US_STOCK_TICKERS = {
    "US0846707026": "BRK-B",       # Berkshire Hathaway
    "US02079K3059": "GOOGL",       # Alphabet Class A
    "US5949181045": "MSFT",        # Microsoft
    "US0378331005": "AAPL",        # Apple
    "US67066G1040": "NVDA",        # NVIDIA
    "US0231351067": "AMZN",        # Amazon
    "US1912161007": "KO",          # Coca-Cola
    "US00724F1012": "ADBE",        # Adobe
    "US88160R1014": "TSLA",        # Tesla
    "US8740391003": "TSM",         # TSMC ADR
    "US5533681012": "MP",          # MP Materials
    "US5949724083": "MSTR",        # MicroStrategy
    "US92922P1066": "WTI",         # W&T Offshore
    "US6974351057": "PANW",        # Palo Alto Networks
    "US5398301094": "LMT",         # Lockheed Martin
    "US30303M1027": "META",        # Meta
    "US5024311095": "LLY",         # Eli Lilly
    "US4781601046": "JNJ",         # Johnson & Johnson
    "US7427181091": "PG",          # Procter & Gamble
    "US0970231058": "BA",          # Boeing
    "US6541061031": "NKE",         # Nike
    "US2546871060": "DIS",         # Walt Disney
    "US0605051046": "BAC",         # Bank of America
    "US46625H1005": "JPM",         # JPMorgan Chase
    "US62914V1061": "NIO",         # NIO
    "US98422D1054": "XPEV",        # XPeng
    "DK0062498333": "NVO",         # Novo Nordisk (ADR, returns USD)
}

# Non-USD foreign stocks that need explicit tickers + currency handling
FOREIGN_STOCK_TICKERS = {
    # Japanese (returns JPY)
    "JP3436100006": ("9984.T", "JPY"),      # SoftBank Tokyo
    # Hong Kong (returns HKD)  
    "CNE100000296": ("1211.HK", "HKD"),     # BYD Hong Kong
    # German (returns EUR)
    "DE000ENER6Y0": ("ENR.DE", "EUR"),      # Siemens Energy
    "DE0007030009": ("RHM.DE", "EUR"),      # Rheinmetall
    "DE0005810055": ("DBK.DE", "EUR"),      # Deutsche Bank
    "DE0007164600": ("SAP.DE", "EUR"),      # SAP SE
    "DE000A1EWWW0": ("ADS.DE", "EUR"),      # Adidas
    "DE0007236101": ("SIE.DE", "EUR"),      # Siemens
    "DE0008404005": ("ALV.DE", "EUR"),      # Allianz
    "DE0007100000": ("MBG.DE", "EUR"),      # Mercedes-Benz
    "DE0005557508": ("DTE.DE", "EUR"),      # Deutsche Telekom
    "DE000BASF111": ("BAS.DE", "EUR"),      # BASF
    "DE0008232125": ("LHA.DE", "EUR"),      # Lufthansa
    # UK (check currency - some are USD, some GBP)
    "JE00B1VS3333": ("PHAG.L", "USD"),      # Physical Silver (WisdomTree)
    # French
    "FR0000121014": ("MC.PA", "EUR"),       # LVMH
    # Danish (returns DKK)
    "DK0010268606": ("NOVO-B.CO", "DKK"),   # Novo Nordisk (Copenhagen)
    # Dutch (returns EUR)
    "NL0010273215": ("ASML.AS", "EUR"),     # ASML
    # UK
    "GB0002374006": ("DGE.L", "GBP"),       # Diageo
}

# ETFs that can use ISIN directly (most work!) - specify currency for conversion
# These are verified to work with yf.Ticker(ISIN)
ETF_ISIN_CURRENCY = {
    "IE00B4L5Y983": "USD",   # Core MSCI World USD (Acc) - returns USD
    "IE00B5BMR087": "EUR",   # Core S&P 500 USD (Acc) - returns EUR on XETRA
    "LU0908500753": "EUR",   # Core Stoxx Europe 600 EUR (Acc)
    "LU0274211480": "EUR",   # DAX EUR (Acc)
    "IE00B4ND3602": "USD",   # Physical Gold USD (Acc)
    "IE000KHX9DX6": "EUR",   # Energy Transition Metals
    "IE00BYZK4552": "USD",   # Automation & Robotics USD (Acc)
    "IE00BK5BQX27": "EUR",   # FTSE Developed Europe EUR (Acc)
    "IE00BJ5JPG56": "EUR",   # MSCI China USD (Acc) - returns EUR
    "FR0010755611": "EUR",   # MSCI USA 2x Leveraged
    # Other common ETFs
    "IE00B4L5YC18": "USD",   # iShares Core MSCI EM
    "IE00B52MJY50": "USD",   # iShares NASDAQ 100
    "IE00B3XXRP09": "GBP",   # Vanguard S&P 500 (London)
    "IE00BKM4GZ66": "EUR",   # Invesco NASDAQ 100
    "IE00BK5BQT80": "EUR",   # Vanguard FTSE All-World
    "IE00B3RBWM25": "EUR",   # Vanguard FTSE All-World (Dist)
}

# ISINs with NO Yahoo data - will use invested as fallback
NO_YAHOO_DATA = {
    "CA2985962067",   # Eureka Lithium (small-cap Canadian)
    "XF000BTC0017",   # Bitcoin (TR crypto)
    "XF000ETH0019",   # Ethereum (TR crypto)
    "XF000SOL0012",   # Solana (TR crypto)
    "XF000XRP0018",   # XRP (TR crypto)
    "IE0007UPSEA3",   # iBonds Dec 2026 (bond ETF)
    "XS2829810923",   # Mai 2037 (German govt bond)
}

# Legacy mapping for backward compatibility with existing code
KNOWN_ISIN_MAPPINGS = {
    **US_STOCK_TICKERS,
    **{k: v[0] for k, v in FOREIGN_STOCK_TICKERS.items()},
}


def _load_json_cache(path: Path) -> Dict:
    """Load a JSON cache file."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except:
            pass
    return {}


def _save_json_cache(path: Path, data: Dict):
    """Save data to a JSON cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ============================================================================
# FX RATE FUNCTIONS
# ============================================================================

def get_fx_rates() -> Dict[str, float]:
    """
    Get current FX rates for converting to EUR.
    Returns dict with keys: 'EURUSD', 'JPYEUR', 'HKDEUR', 'GBPEUR', 'DKKEUR'
    """
    rates = {}
    try:
        # EUR/USD rate (to convert USD to EUR: price_usd / rate)
        rates['EURUSD'] = yf.Ticker('EURUSD=X').fast_info.last_price
        # JPY/EUR rate (to convert JPY to EUR: price_jpy * rate)
        rates['JPYEUR'] = yf.Ticker('JPYEUR=X').fast_info.last_price
        # HKD/EUR rate
        rates['HKDEUR'] = yf.Ticker('HKDEUR=X').fast_info.last_price
        # GBP/EUR rate
        rates['GBPEUR'] = yf.Ticker('GBPEUR=X').fast_info.last_price
        # DKK/EUR rate
        rates['DKKEUR'] = yf.Ticker('DKKEUR=X').fast_info.last_price
        log.info(f"FX rates: EUR/USD={rates['EURUSD']:.4f}")
    except Exception as e:
        log.warning(f"Failed to get FX rates: {e}")
        # Fallback rates
        rates = {'EURUSD': 1.10, 'JPYEUR': 0.0061, 'HKDEUR': 0.12, 'GBPEUR': 1.17, 'DKKEUR': 0.13}
    return rates


def convert_to_eur(price: float, currency: str, fx_rates: Dict[str, float]) -> float:
    """Convert a price from any currency to EUR."""
    if currency == 'EUR':
        return price
    elif currency == 'USD':
        return price / fx_rates.get('EURUSD', 1.10)
    elif currency == 'JPY':
        return price * fx_rates.get('JPYEUR', 0.0061)
    elif currency == 'HKD':
        return price * fx_rates.get('HKDEUR', 0.12)
    elif currency == 'GBP':
        return price * fx_rates.get('GBPEUR', 1.17)
    elif currency == 'DKK':
        return price * fx_rates.get('DKKEUR', 0.13)
    else:
        log.warning(f"Unknown currency {currency}, assuming EUR")
        return price


def get_current_price_eur(isin: str, name: str = "") -> Optional[Tuple[float, str]]:
    """
    Get current price for an ISIN, converted to EUR.
    
    Returns:
        (price_eur, ticker) or None if not available
    """
    # Skip known no-data ISINs
    if isin in NO_YAHOO_DATA or isin.startswith('XF000'):
        return None
    
    fx_rates = get_fx_rates()
    
    # 1. Check if it's a US stock (needs explicit ticker)
    if isin in US_STOCK_TICKERS:
        ticker = US_STOCK_TICKERS[isin]
        try:
            t = yf.Ticker(ticker)
            price_usd = t.fast_info.last_price
            price_eur = convert_to_eur(price_usd, 'USD', fx_rates)
            return (price_eur, ticker)
        except Exception as e:
            log.debug(f"Failed to get price for {ticker}: {e}")
            return None
    
    # 2. Check if it's a foreign stock with explicit ticker + currency
    if isin in FOREIGN_STOCK_TICKERS:
        ticker, currency = FOREIGN_STOCK_TICKERS[isin]
        try:
            t = yf.Ticker(ticker)
            price = t.fast_info.last_price
            price_eur = convert_to_eur(price, currency, fx_rates)
            return (price_eur, ticker)
        except Exception as e:
            log.debug(f"Failed to get price for {ticker}: {e}")
            return None
    
    # 3. Try ISIN directly (works for most ETFs)
    try:
        t = yf.Ticker(isin)
        price = t.fast_info.last_price
        # Get currency from ticker info
        currency = t.info.get('currency', 'EUR')
        price_eur = convert_to_eur(price, currency, fx_rates)
        return (price_eur, isin)
    except Exception as e:
        log.debug(f"ISIN direct lookup failed for {isin}: {e}")
    
    # 4. Check ETF_ISIN_CURRENCY for known currency
    if isin in ETF_ISIN_CURRENCY:
        currency = ETF_ISIN_CURRENCY[isin]
        try:
            t = yf.Ticker(isin)
            price = t.fast_info.last_price
            price_eur = convert_to_eur(price, currency, fx_rates)
            return (price_eur, isin)
        except:
            pass
    
    return None


def _lookup_isin_openfigi(isin: str) -> Optional[str]:
    """
    Look up ISIN using OpenFIGI API to get a ticker symbol.
    OpenFIGI is a free, industry-standard API for financial instrument identification.
    """
    try:
        url = "https://api.openfigi.com/v3/mapping"
        headers = {"Content-Type": "application/json"}
        payload = [{"idType": "ID_ISIN", "idValue": isin}]
        
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code != 200:
            return None
            
        data = resp.json()
        if not data or not data[0].get("data"):
            return None
        
        # Get the first result - prefer common stock or ETF
        results = data[0]["data"]
        for item in results:
            ticker = item.get("ticker")
            exch_code = item.get("exchCode", "")
            mkt_sector = item.get("marketSector", "")
            
            if ticker:
                # Try to determine the right Yahoo suffix
                suffix = ""
                if exch_code == "GY":  # German XETRA
                    suffix = ".DE"
                elif exch_code == "GF":  # Frankfurt
                    suffix = ".F"
                elif exch_code == "LN":  # London
                    suffix = ".L"
                elif exch_code == "NA":  # Amsterdam
                    suffix = ".AS"
                elif exch_code == "SW":  # Swiss
                    suffix = ".SW"
                elif exch_code == "FP":  # Paris
                    suffix = ".PA"
                elif exch_code in ("US", "UN", "UW", "UQ"):  # US exchanges
                    suffix = ""
                
                return ticker + suffix
        
        return None
    except Exception as e:
        log.debug(f"OpenFIGI lookup failed for {isin}: {e}")
        return None


def _lookup_isin_yfinance_search(isin: str) -> Optional[str]:
    """Try to find the symbol by searching yfinance directly."""
    try:
        # yfinance can sometimes resolve ISIN directly
        ticker = yf.Ticker(isin)
        info = ticker.info
        if info and info.get("symbol") and info.get("regularMarketPrice"):
            return info["symbol"]
    except:
        pass
    
    # Try with common exchange suffixes
    suffixes = ["", ".DE", ".F", ".L", ".AS", ".SW", ".PA"]
    for suffix in suffixes:
        try:
            test_symbol = isin + suffix
            ticker = yf.Ticker(test_symbol)
            # Quick check - try to get recent history
            hist = ticker.history(period="5d")
            if len(hist) > 0:
                return test_symbol
        except:
            continue
    
    return None


def isin_to_symbol(isin: str, name: str = "") -> Optional[str]:
    """
    Convert ISIN to Yahoo Finance symbol.
    Uses multiple lookup methods with caching.
    """
    if not isin:
        return None
    
    # 1. Check known mappings (fastest)
    if isin in KNOWN_ISIN_MAPPINGS:
        return KNOWN_ISIN_MAPPINGS[isin]
    
    # 2. Check cache
    cache = _load_json_cache(ISIN_SYMBOL_CACHE_FILE)
    if isin in cache:
        symbol = cache[isin]
        if symbol:  # Can be None if previously failed
            return symbol
        # If it's None, we already tried and failed - don't retry
        return None
    
    log.info(f"Looking up symbol for ISIN {isin} ({name})...")
    
    # 3. Try OpenFIGI API
    symbol = _lookup_isin_openfigi(isin)
    if symbol:
        log.info(f"  OpenFIGI found: {symbol}")
        cache[isin] = symbol
        _save_json_cache(ISIN_SYMBOL_CACHE_FILE, cache)
        return symbol
    
    # 4. Try yfinance search as fallback
    symbol = _lookup_isin_yfinance_search(isin)
    if symbol:
        log.info(f"  yfinance search found: {symbol}")
        cache[isin] = symbol
        _save_json_cache(ISIN_SYMBOL_CACHE_FILE, cache)
        return symbol
    
    # 5. Mark as not found in cache to avoid repeated lookups
    log.warning(f"  Could not find Yahoo symbol for {isin} ({name})")
    cache[isin] = None
    _save_json_cache(ISIN_SYMBOL_CACHE_FILE, cache)
    return None


def extract_isin_from_icon(icon: str) -> Optional[str]:
    """Extract ISIN from transaction icon field like 'logos/IE00B5BMR087/v2'."""
    if not icon:
        return None
    match = re.search(r'logos/([A-Z0-9]{12})', icon)
    return match.group(1) if match else None


def get_price_at_date(isin: str, name: str, date: datetime) -> Optional[float]:
    """
    Get the closing price for a specific ISIN on a specific date.
    Uses cache to avoid redundant downloads.
    """
    date_str = date.strftime("%Y-%m-%d")
    
    # Check cache first
    cache = _load_json_cache(PRICE_CACHE_FILE)
    if isin in cache and date_str in cache[isin]:
        return cache[isin][date_str]
    
    # Get Yahoo symbol
    symbol = isin_to_symbol(isin, name)
    if not symbol:
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        # Fetch a small window around the date (handles weekends/holidays)
        start = date - timedelta(days=5)
        end = date + timedelta(days=1)
        
        hist = ticker.history(start=start, end=end)
        
        if len(hist) == 0:
            return None
        
        # Get the closest date <= requested date
        hist.index = hist.index.tz_localize(None)
        target_date = pd.Timestamp(date_str)
        
        # Filter to dates <= target
        valid = hist[hist.index <= target_date]
        if len(valid) > 0:
            price = float(valid["Close"].iloc[-1])
            
            # Cache it
            if isin not in cache:
                cache[isin] = {}
            cache[isin][date_str] = price
            _save_json_cache(PRICE_CACHE_FILE, cache)
            
            return price
        
        return None
        
    except Exception as e:
        log.debug(f"Failed to get price for {symbol} on {date_str}: {e}")
        return None


def get_prices_for_dates(isin: str, name: str, dates: List[datetime]) -> Dict[str, float]:
    """
    Get prices for multiple dates efficiently.
    Downloads missing data in batches, uses cache for existing.
    """
    if not dates:
        return {}
    
    date_strs = [d.strftime("%Y-%m-%d") for d in dates]
    
    # Load cache
    cache = _load_json_cache(PRICE_CACHE_FILE)
    isin_cache = cache.get(isin, {})
    
    # Find which dates we already have
    result = {}
    missing_dates = []
    
    for date_str in date_strs:
        if date_str in isin_cache:
            result[date_str] = isin_cache[date_str]
        else:
            missing_dates.append(date_str)
    
    if not missing_dates:
        return result
    
    # Get Yahoo symbol
    symbol = isin_to_symbol(isin, name)
    if not symbol:
        return result
    
    # Download prices for the missing date range
    min_date = min(missing_dates)
    max_date = max(missing_dates)
    
    try:
        ticker = yf.Ticker(symbol)
        start = datetime.strptime(min_date, "%Y-%m-%d") - timedelta(days=5)
        end = datetime.strptime(max_date, "%Y-%m-%d") + timedelta(days=1)
        
        hist = ticker.history(start=start, end=end)
        
        if len(hist) == 0:
            return result
        
        hist.index = hist.index.tz_localize(None)
        hist = hist.sort_index()
        
        # For each missing date, find the closest valid price
        for date_str in missing_dates:
            target = pd.Timestamp(date_str)
            
            # Get dates <= target
            valid = hist[hist.index <= target]
            if len(valid) > 0:
                price = float(valid["Close"].iloc[-1])
                result[date_str] = price
                isin_cache[date_str] = price
        
        # Save updated cache
        cache[isin] = isin_cache
        _save_json_cache(PRICE_CACHE_FILE, cache)
        
    except Exception as e:
        log.warning(f"Failed to fetch prices for {symbol}: {e}")
    
    return result


def build_portfolio_history(
    transactions: List[Dict],
    positions: List[Dict],
    current_total: float,
    cash: float = 0,
    progress_callback=None,
    return_position_histories: bool = False
) -> List[Dict]:
    """
    Build accurate portfolio value history using transaction data and market prices.
    
    This calculates actual portfolio value at each point by:
    1. Tracking when each position was bought/sold and at what quantity
    2. Getting historical prices for each holding at each date
    3. Calculating portfolio value = sum(holdings * prices) at each date
    
    Args:
        transactions: List of transaction dicts from TR
        positions: List of current position dicts
        current_total: Current total portfolio value
        cash: Current cash balance
        progress_callback: Optional callback(step, total, message) for progress updates
        return_position_histories: If True, also return per-position price histories
        
    Returns:
        List of {date, invested, value} dicts
        OR if return_position_histories is True:
        Tuple of (history_list, position_histories_dict)
    """
    log.info("Building portfolio value history from transactions and market prices...")
    
    if progress_callback:
        progress_callback(0, 100, "Analyzing transactions...")
    
    # Buy/sell transaction subtitles (German)
    BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
    SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
    
    # Build position name lookup
    isin_to_name = {p.get("isin", ""): p.get("name", "") for p in positions}
    
    # Track holdings changes: {isin: [(date, quantity_change, cost_basis_change)]}
    holdings_changes: Dict[str, List[Tuple[datetime, float, float]]] = {}
    
    for txn in transactions:
        subtitle = txn.get("subtitle", "")
        icon = txn.get("icon", "")
        amount = txn.get("amount", 0)
        timestamp = txn.get("timestamp", "")
        
        if not timestamp:
            continue
        
        try:
            date = datetime.fromisoformat(timestamp.replace("+0000", "+00:00")).replace(tzinfo=None)
        except:
            continue
        
        isin = extract_isin_from_icon(icon)
        if not isin:
            continue
        
        # We need quantity info which isn't in timeline - estimate from amount and avg buy
        # For now, track by cost basis (amount spent)
        if subtitle in BUY_SUBTITLES:
            cost = abs(float(amount)) if amount else 0
            holdings_changes.setdefault(isin, []).append((date, cost, True))
        elif subtitle in SELL_SUBTITLES:
            cost = abs(float(amount)) if amount else 0
            holdings_changes.setdefault(isin, []).append((date, cost, False))
    
    if not holdings_changes:
        log.warning("No holdings changes found in transactions")
        return []
    
    # Get all unique transaction dates
    all_dates = set()
    for changes in holdings_changes.values():
        for date, _, _ in changes:
            all_dates.add(date.date())
    
    if not all_dates:
        return []
    
    # Generate a reasonable set of dates for history (monthly + all transaction dates)
    start_date = min(all_dates)
    end_date = datetime.now().date()
    
    # Monthly dates
    history_dates = set()
    current = start_date.replace(day=1)
    while current <= end_date:
        history_dates.add(current)
        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    # Add all transaction dates
    history_dates.update(all_dates)
    # Add today
    history_dates.add(end_date)
    
    sorted_dates = sorted(history_dates)
    
    if progress_callback:
        progress_callback(10, 100, f"Processing {len(holdings_changes)} instruments...")
    
    # For each ISIN, get prices at all history dates
    isin_prices: Dict[str, Dict[str, float]] = {}
    isins = list(holdings_changes.keys())
    
    for idx, isin in enumerate(isins):
        name = isin_to_name.get(isin, isin)
        
        if progress_callback:
            pct = 10 + int(60 * (idx + 1) / len(isins))
            progress_callback(pct, 100, f"Fetching prices for {name[:30]}...")
        
        # Get prices for all dates we need
        dates_as_dt = [datetime.combine(d, datetime.min.time()) for d in sorted_dates]
        prices = get_prices_for_dates(isin, name, dates_as_dt)
        isin_prices[isin] = prices
        
        if prices:
            log.info(f"Got {len(prices)} prices for {name} ({isin})")
        else:
            log.warning(f"No prices found for {name} ({isin})")
    
    if progress_callback:
        progress_callback(70, 100, "Calculating portfolio values...")
    
    # Build cumulative holdings at each date
    # holdings[isin] = cumulative invested amount at each date
    holdings_at_date: Dict[str, Dict[str, float]] = {isin: {} for isin in holdings_changes}
    
    for isin, changes in holdings_changes.items():
        sorted_changes = sorted(changes, key=lambda x: x[0])
        cumulative = 0.0
        
        for date, amount, is_buy in sorted_changes:
            if is_buy:
                cumulative += amount
            else:
                cumulative = max(0, cumulative - amount)
            holdings_at_date[isin][date.strftime("%Y-%m-%d")] = cumulative
    
    # Now calculate portfolio value at each history date
    # We use RELATIVE price movement to avoid currency issues
    # value_at_date = invested × (price_at_date / first_price_after_purchase)
    history = []
    
    # For each ISIN, find the first price after each purchase to use as baseline
    # This gives us relative performance in the original purchase currency
    
    for date in sorted_dates:
        date_str = date.strftime("%Y-%m-%d")
        total_invested = 0.0
        total_value = 0.0
        
        for isin in holdings_changes.keys():
            # Get cumulative invested at this date (use last known value before date)
            invested = 0.0
            last_change_date = None
            for d in sorted([d for d in holdings_at_date[isin].keys() if d <= date_str]):
                invested = holdings_at_date[isin][d]
                last_change_date = d
            
            if invested <= 0:
                continue
            
            total_invested += invested
            
            # Get prices for this ISIN
            prices = isin_prices.get(isin, {})
            price_at_date = prices.get(date_str)
            
            if price_at_date and last_change_date:
                # Find baseline price (first available price on or after last change)
                baseline_price = None
                for check_date in sorted(prices.keys()):
                    if check_date >= last_change_date:
                        baseline_price = prices[check_date]
                        break
                
                if baseline_price and baseline_price > 0:
                    # Calculate value using relative price movement
                    # This works regardless of currency because it's a ratio
                    growth_factor = price_at_date / baseline_price
                    value_at_date = invested * growth_factor
                    total_value += value_at_date
                else:
                    total_value += invested
            else:
                # No price data - use invested as fallback
                total_value += invested
        
        if total_invested > 0:
            history.append({
                "date": date_str,
                "invested": round(total_invested, 2),
                "value": round(total_value, 2)
            })
    
    if progress_callback:
        progress_callback(100, 100, f"Done! Generated {len(history)} data points.")
    
    log.info(f"Built portfolio history with {len(history)} data points")
    
    if return_position_histories:
        # Build per-position histories for asset class filtering
        # Format: {isin: {history: [{date, price}], quantity, instrumentType, name}}
        position_histories = {}
        
        # Build position lookup for metadata
        pos_lookup = {p.get('isin', ''): p for p in positions}
        
        for isin in holdings_changes.keys():
            pos = pos_lookup.get(isin, {})
            prices = isin_prices.get(isin, {})
            
            # Build price history list
            price_history = []
            for date_str in sorted(prices.keys()):
                price = prices.get(date_str)
                if price and price > 0:
                    price_history.append({
                        'date': date_str,
                        'price': price,
                    })
            
            if price_history:
                position_histories[isin] = {
                    'history': price_history,
                    'quantity': pos.get('quantity', 0),
                    'instrumentType': pos.get('instrumentType', ''),
                    'name': pos.get('name', isin),
                }
                log.info(f"Built position history for {pos.get('name', isin)}: {len(price_history)} points")
        
        return history, position_histories
    
    return history


def update_position_values(positions: List[Dict]) -> List[Dict]:
    """
    Update position values with current market prices converted to EUR.
    
    This function:
    1. Gets current prices from Yahoo Finance
    2. Converts all prices to EUR using live FX rates
    3. Calculates current value = quantity × price_eur
    4. Calculates profit = value - invested
    
    Returns updated positions list.
    """
    log.info("Updating position values with current EUR prices...")
    
    fx_rates = get_fx_rates()
    updated = []
    total_value = 0
    total_invested = 0
    
    for pos in positions:
        isin = pos.get("isin", "")
        name = pos.get("name", "")
        qty = pos.get("quantity", 0)
        invested = pos.get("invested", 0)
        
        total_invested += invested
        
        # Try to get current price in EUR
        result = get_current_price_eur(isin, name)
        
        if result:
            price_eur, ticker = result
            value = qty * price_eur
            profit = value - invested
            
            updated.append({
                **pos,
                "currentPrice": round(price_eur, 2),
                "value": round(value, 2),
                "profit": round(profit, 2),
                "_ticker": ticker,  # Debug info
            })
            total_value += value
            log.debug(f"{name[:30]}: qty={qty:.2f} × {price_eur:.2f} EUR = {value:.2f} EUR (gain: {profit/invested*100 if invested else 0:.1f}%)")
        else:
            # No price data - use invested as fallback
            updated.append({
                **pos,
                "value": invested,
                "profit": 0,
            })
            total_value += invested
            log.debug(f"{name[:30]}: No price data, using invested={invested:.2f} EUR")
    
    log.info(f"Position values updated: {len(updated)} positions, total={total_value:,.2f} EUR (invested={total_invested:,.2f} EUR)")
    return updated


def calculate_and_save_history(force_rebuild: bool = False) -> Tuple[bool, str, List[Dict]]:
    """
    Calculate portfolio history and save to cache.
    Also updates current position values with live EUR prices.
    
    This is the main entry point for portfolio recalculation.
    
    Returns:
        (success, message, history)
    """
    # Load required data from caches
    portfolio_cache_file = CACHE_DIR / "portfolio_cache.json"
    transactions_cache_file = CACHE_DIR / "transactions_cache.json"
    
    if not portfolio_cache_file.exists():
        return False, "No portfolio data found. Please sync with TR first.", []
    
    if not transactions_cache_file.exists():
        return False, "No transaction data found. Please sync with TR first.", []
    
    try:
        portfolio_data = json.loads(portfolio_cache_file.read_text(encoding="utf-8"))
        transactions = json.loads(transactions_cache_file.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"Failed to load cached data: {e}", []
    
    data = portfolio_data.get("data", {})
    positions = data.get("positions", [])
    cash = data.get("cash", 0)
    
    if not positions:
        return False, "No positions found in portfolio data.", []
    
    if not transactions:
        return False, "No transactions found. History requires transaction data.", []
    
    # Check if we already have valid cached history
    if not force_rebuild and PORTFOLIO_HISTORY_CACHE_FILE.exists():
        try:
            cached = json.loads(PORTFOLIO_HISTORY_CACHE_FILE.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
            
            # Cache valid for 24 hours
            if (datetime.now() - cached_at).total_seconds() < 24 * 3600:
                history = cached.get("history", [])
                if history:
                    log.info(f"Using cached portfolio history ({len(history)} points)")
                    return True, f"Using cached history ({len(history)} points)", history
        except Exception as e:
            log.warning(f"Failed to load history cache: {e}")
    
    # =========================================================================
    # UPDATE CURRENT POSITION VALUES WITH LIVE EUR PRICES
    # =========================================================================
    log.info("Updating position values with current EUR prices...")
    updated_positions = update_position_values(positions)
    
    # Calculate new totals
    total_value = sum(p.get("value", p.get("invested", 0)) for p in updated_positions)
    total_invested = sum(p.get("invested", 0) for p in updated_positions)
    total_profit = total_value - total_invested
    
    log.info(f"Portfolio totals: value={total_value:,.2f} EUR, invested={total_invested:,.2f} EUR, profit={total_profit:,.2f} EUR")
    
    # =========================================================================
    # BUILD PORTFOLIO HISTORY WITH PER-POSITION HISTORIES
    # =========================================================================
    log.info("Building new portfolio history...")
    result = build_portfolio_history(
        transactions=transactions,
        positions=updated_positions,
        current_total=total_value + cash,
        cash=cash,
        return_position_histories=True
    )
    
    if isinstance(result, tuple):
        history, position_histories = result
    else:
        history = result
        position_histories = {}
    
    if not history:
        return False, "Failed to build history. Check logs for details.", []
    
    # Update the last history point with the calculated current value
    if history:
        history[-1]["value"] = round(total_value, 2)
    
    log.info(f"Portfolio history: {len(history)} points, first={history[0]['date']}, last={history[-1]['date']}")
    if position_histories:
        log.info(f"Position histories: {len(position_histories)} instruments with price data")
    
    # =========================================================================
    # SAVE ALL UPDATES TO CACHE
    # =========================================================================
    try:
        # Save history cache
        cache_data = {
            "cached_at": datetime.now().isoformat(),
            "history": history
        }
        _save_json_cache(PORTFOLIO_HISTORY_CACHE_FILE, cache_data)
        
        # Update portfolio_cache.json with updated positions and values
        data["positions"] = updated_positions
        data["totalValue"] = round(total_value + cash, 2)
        data["totalInvested"] = round(total_invested, 2)
        data["totalProfit"] = round(total_profit, 2)
        data["history"] = history
        data["positionHistories"] = position_histories  # Per-position histories for filtering
        portfolio_data["data"] = data
        portfolio_data["cached_at"] = datetime.now().isoformat()
        portfolio_cache_file.write_text(json.dumps(portfolio_data, indent=2), encoding="utf-8")
        
        log.info(f"Saved portfolio cache: totalValue={total_value + cash:,.2f} EUR, {len(position_histories)} position histories")
        
    except Exception as e:
        log.warning(f"Failed to save cache: {e}")
    
    return True, f"Successfully calculated {len(history)} history points. Total value: {total_value + cash:,.2f} EUR", history

