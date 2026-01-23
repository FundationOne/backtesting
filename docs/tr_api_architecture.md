# Trade Republic API Architecture & Data Flow

**Last Updated:** 2026-01-22  
**Status:** Working implementation - all features integrated into TR Sync

---

## Executive Summary

This document captures the technical findings about Trade Republic (TR) API integration, what works, what doesn't, and the architectural decisions made. **READ THIS BEFORE MAKING CHANGES.**

**Key Design Decision:** Everything happens in ONE TR Sync click. No separate recalculation steps.

---

## Requirements Status (2026-01-22)

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| TWR calculation for all chart traces | ✅ Done | `_calculate_twr_series()` in `portfolio_analysis.py` - chains period returns, starts at 0% |
| Added Capital line solid | ✅ Done | `line=dict(color='#f59e0b', width=2)` - solid by default |
| Asset class filter impacts charts | ✅ Done | `_build_position_histories_from_yahoo()` in `tr_api.py` generates positionHistories during sync |
| Asset type detection | ⚠️ Heuristic | TR doesn't provide `instrumentType`, using name-based heuristics in `get_position_asset_class()` |
| Image/Logo loading | ✅ Done | Uses TR `imageId` when available, falls back to colored initials (no external API dependencies) |

---

## 1. TR API Access Methods

### 1.1 Authentication Options

| Method | How It Works | Status |
|--------|--------------|--------|
| **Web Login (Cookies)** | User logs in via browser, session cookies stored | ✅ WORKING - This is what we use |
| **Keyfile (pytr)** | Phone + PIN + keyfile.pem for API auth | ❌ NOT USED - Requires 2FA setup per device |

**Key Finding:** The user authenticates via web browser. The `pytr` library's keyfile-based auth requires a separate 2FA flow that most users won't do. We work around this by using cached data.

### 1.2 pytr Library Endpoints

The `pytr` library (`from pytr.api import TradeRepublicApi`) provides these methods:

| Method | Purpose | Returns | Status |
|--------|---------|---------|--------|
| `portfolio()` | Current positions | List of holdings with qty, avgBuyIn | ✅ Works |
| `portfolio_history(timeframe)` | Aggregate portfolio value history | Total value per date | ✅ Works |
| `performance_history(isin, timeframe, exchange)` | Per-instrument price history | Price data per date | ⚠️ Unreliable |
| `timeline_transactions()` | Transaction history | Buys, sells, dividends, etc. | ✅ Works |
| `instrument_details(isin)` | Instrument metadata | typeId, imageId, name | ⚠️ Needs testing |

### 1.3 What the TR API Does NOT Provide

- **instrumentType on positions**: The `portfolio()` response does NOT include asset type (stock/ETF/crypto/bond)
- **Reliable per-position history**: `performance_history()` fails for many instruments (wrong exchange, delisted, etc.)
- **Historical quantity tracking**: No way to know how many shares you held at a past date

---

## 2. Data Architecture

### 2.1 Cache Files

All cached data is stored in `~/.pytr/` directory:

| File | Contents | Updated By |
|------|----------|------------|
| `portfolio_cache.json` | Complete portfolio snapshot + positionHistories | TR Sync button |
| `transactions_cache.json` | Full transaction history | TR Sync button |
| `instrument_cache.json` | ISIN → name mapping | TR Sync button |
| `benchmark_cache.json` | Benchmark index prices | Benchmark selection |
| `price_cache.json` | Historical prices from Yahoo | TR Sync (via positionHistories) |
| `isin_symbol_cache.json` | ISIN → Yahoo ticker mapping | TR Sync (via positionHistories) |

### 2.2 portfolio_cache.json Structure

```json
{
  "success": true,
  "cached_at": "2026-01-22T...",
  "data": {
    "totalValue": 123456.78,
    "investedAmount": 100000.00,
    "cash": 500.00,
    "totalProfit": 23456.78,
    "totalProfitPercent": 23.46,
    "positions": [
      {
        "isin": "US5949181045",
        "name": "Microsoft",
        "quantity": 10,
        "averageBuyIn": 350.00,
        "value": 4200.00,
        "invested": 3500.00,
        "profit": 700.00,
        "currentPrice": 420.00,
        "instrumentType": "",  // <-- EMPTY from TR API!
        "_ticker": "MSFT"
      }
    ],
    "transactions": [...],
    "history": [
      {"date": "2024-01-01", "invested": 50000, "value": 52000},
      ...
    ],
    "positionHistories": {  // <-- Added by Recalculate History
      "US5949181045": {
        "history": [{"date": "2024-01-01", "price": 380.50}, ...],
        "quantity": 10,
        "instrumentType": "",
        "name": "Microsoft"
      }
    }
  }
}
```

### 2.3 Single-Step Data Flow (TR Sync)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TR SYNC (One Click)                          │
│  (components/tr_api.py → portfolio_cache.json)                       │
│                                                                      │
│  1. Fetches current positions from TR                                │
│  2. Fetches transaction history from TR                              │
│  3. Fetches aggregate portfolio history from TR                      │
│  4. Builds positionHistories from YAHOO FINANCE (not TR!)            │
│     - Uses transactions to find all ISINs with activity              │
│     - Fetches historical prices from Yahoo for each ISIN             │
│     - Stores in positionHistories for chart filtering                │
│  5. Saves everything to portfolio_cache.json                         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      PORTFOLIO ANALYSIS PAGE                         │
│  (pages/portfolio_analysis.py)                                       │
│                                                                      │
│  • Reads portfolio_cache.json                                        │
│  • Uses positionHistories for asset class chart filtering            │
│  • Uses heuristics for asset class detection (name-based)            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Asset Class Detection

### 3.1 The Problem

TR API does NOT provide `instrumentType` on positions. The field is always empty.

### 3.2 The Solution: Heuristics

`get_position_asset_class()` in `portfolio_analysis.py` uses this fallback logic:

1. Check `instrumentType` field (always empty from TR)
2. Check other fields: `assetClass`, `asset_class`, `assetType`, `type`, `category`
3. **Heuristics based on name:**
   - Contains "etf", "ishares", "vanguard", "xtrackers" → ETF
   - Contains "bitcoin", "ethereum", "crypto" → Crypto
   - Contains "bond", "anleihe" → Bond
   - Default → Stock

### 3.3 Limitations

- Relies on instrument names being descriptive
- May misclassify obscure instruments
- Cannot distinguish between stocks and stock ETFs without clear naming

---

## 4. Chart Filtering by Asset Class

### 4.1 How It Works

1. User selects asset classes in filter (e.g., "ETF only")
2. `_build_filtered_history()` filters `positionHistories` by asset class
3. Aggregates filtered position values per date
4. Chart shows filtered history

### 4.2 Requirements

- **positionHistories is generated during TR Sync** (automatically via Yahoo Finance)
- No separate "Recalculate History" step needed
- Without positionHistories, filter has no effect on charts (only holdings table)

### 4.3 Data Format Expected

```python
positionHistories = {
    "ISIN": {
        "history": [{"date": "YYYY-MM-DD", "price": float}, ...],
        "quantity": float,
        "instrumentType": str,  # May be empty
        "name": str
    }
}
```

---

## 5. Price Data Sources

### 5.1 Yahoo Finance (Primary)

Used by `portfolio_history.py` for historical prices. Requires ISIN → ticker mapping.

| Instrument Type | Lookup Method | Example |
|-----------------|---------------|---------|
| US Stocks | Hardcoded mapping | US5949181045 → MSFT |
| EU/UK Stocks | OpenFIGI API → Yahoo ticker | DE0007164600 → SAP.DE |
| ETFs | ISIN directly | IE00B4L5Y983 works as-is |
| Crypto | NOT SUPPORTED | XF000BTC0017 → no data |

### 5.2 Known No-Data ISINs

These ISINs have no Yahoo Finance data (defined in `NO_YAHOO_DATA`):
- `CA2985962067` - Eureka Lithium (small-cap)
- `XF000BTC0017` - Bitcoin (TR crypto)
- `XF000ETH0019` - Ethereum (TR crypto)
- `XF000SOL0012` - Solana (TR crypto)
- `XF000XRP0018` - XRP (TR crypto)
- `IE0007UPSEA3` - iBonds (bond ETF)

### 5.3 Currency Conversion

All prices are converted to EUR using live FX rates from Yahoo:
- `EURUSD=X`, `JPYEUR=X`, `HKDEUR=X`, `GBPEUR=X`, `DKKEUR=X`

---

## 6. TWR (Time-Weighted Return) Calculation

### 6.1 Formula

TWR chains period returns to exclude the effect of cash flows:

```python
# For each period:
cash_flow = invested[i] - invested[i-1]
adjusted_end_value = value[i] - cash_flow
period_return = (adjusted_end_value / value[i-1]) - 1

# Chain all periods:
cumulative_factor = product(1 + period_return)
twr_percent = (cumulative_factor - 1) * 100
```

This gives a series that:
- **Starts at 0%** on the first date
- **Excludes cash flow effects** - adding money doesn't artificially reduce the return
- **Shows true investment performance** - what you'd see if you made one lump-sum investment

### 6.2 Implementation Location

- `pages/portfolio_analysis.py` - `_calculate_twr_series()` function
- Applied to both portfolio AND benchmark traces for fair comparison

---

## 7. Logo/Icon Loading

### 7.1 Strategy

**Simple approach - no external API dependencies:**

1. **If TR provides `imageId`** → Use TR's image endpoint: `https://assets.traderepublic.com/img/{imageId}/light.min.png`
2. **Otherwise** → Show colored initials based on asset class:
   - ETF: Blue (#3b82f6)
   - Stock: Green (#10b981)
   - Crypto: Orange (#f59e0b)
   - Bond: Purple (#8b5cf6)

### 7.2 Why No External Logo APIs

- **Clearbit** - Deprecated/unreliable
- **Google Favicon** - Only returns small favicons, not good for display
- **Company name → domain mapping** - Doesn't scale, breaks for new users with different stocks

The initials approach is clean, works for any portfolio, and doesn't require maintaining mappings.

---

## 8. What We Tried That DIDN'T Work

### 8.1 TR performance_history API

**Attempted:** Fetch per-position history directly from TR using `performance_history(isin, timeframe, exchange)`

**Result:** Fails for many instruments:
- Wrong exchange (LSX doesn't have all instruments)
- Delisted instruments
- Bonds and some ETFs not available

**Solution:** Use Yahoo Finance instead (more reliable, works offline with cache)

### 8.2 TR instrument_details for instrumentType

**Attempted:** Fetch instrument metadata to get asset type

**Result:** Requires active connection, adds latency, may not return useful typeId

**Solution:** Use name-based heuristics (works offline, instant)

### 8.3 Keyfile-based Authentication

**Attempted:** Use pytr's standard auth flow with keyfile.pem

**Result:** Requires user to do 2FA setup per device, most users use web login

**Solution:** Support web login via cookies, use cached data

---

## 9. Files Modified (2026-01-22)

| File | Change |
|------|--------|
| `components/tr_api.py` | Added `_build_position_histories_from_yahoo()` method to generate positionHistories during TR Sync |
| `components/portfolio_history.py` | Added `return_position_histories` parameter (kept for manual recalculation if needed) |
| `pages/portfolio_analysis.py` | Already had `_build_filtered_history()` - no changes needed |

---

## 10. Testing Checklist

After making changes, verify:

- [ ] TR Sync completes without error
- [ ] `portfolio_cache.json` contains `positionHistories` with data after sync
- [ ] Asset class detection works for known instruments
- [ ] Chart filtering by asset class updates the chart (not just holdings table)
- [ ] Benchmarks still display correctly
- [ ] TWR calculation matches expected values

---

## 11. Future Improvements

1. **Better instrumentType detection**: Could use TR's `instrument_details` API during sync if connection is available
2. **Crypto price support**: Add CoinGecko or similar API for crypto prices
3. **Caching improvements**: Add TTL-based invalidation
4. **Error handling**: Better feedback when Yahoo Finance fails for an instrument

---

## Appendix A: ISIN → Ticker Mappings

See `portfolio_history.py` for complete mappings:
- `US_STOCK_TICKERS` - US stocks (must use explicit ticker, Yahoo can't lookup US ISINs)
- `FOREIGN_STOCK_TICKERS` - Non-US stocks with currency info
- `ETF_ISIN_CURRENCY` - ETFs that work with ISIN directly
- `NO_YAHOO_DATA` - ISINs with no price data available

---

## Appendix B: Transaction Subtitles (German)

| Subtitle | Meaning | Category |
|----------|---------|----------|
| Kauforder | Buy order | BUY |
| Sparplan ausgeführt | Savings plan executed | BUY |
| Limit-Buy-Order | Limit buy | BUY |
| Verkaufsorder | Sell order | SELL |
| Limit-Sell-Order | Limit sell | SELL |
| Bardividende | Cash dividend | DIVIDEND |
| Einzahlung | Deposit | CASH_IN |
| Zinsen | Interest | CASH_IN |

