# Portfolio Analysis - Feature Specification & Architecture

**Last Updated**: 2026-01-30
**Current Working Commit**: Check with `git log --oneline -1`

---

## 1. FEATURE STATUS

### ✅ IMPLEMENTED & WORKING

| Feature | File(s) | Status | Notes |
|---------|---------|--------|-------|
| TR Authentication (phone/PIN/OTP) | `tr_api.py`, `tr_connector.py` | ✅ Working | WebSocket-based auth |
| Portfolio sync from TR | `tr_api.py` | ✅ Working | Fetches positions, transactions, history |
| Position enrichment (names, symbols) | `tr_api.py` | ✅ Working | Uses instrument details API |
| Portfolio value chart | `portfolio_analysis.py` | ✅ Working | Shows value over time |
| Performance chart (TWR) | `portfolio_analysis.py` | ✅ Working | Time-weighted returns |
| Drawdown chart | `portfolio_analysis.py` | ✅ Working | Peak-to-trough analysis |
| Benchmark comparison | `portfolio_analysis.py`, `benchmark_data.py` | ✅ Working | S&P 500, MSCI World, etc. |
| Holdings table | `portfolio_analysis.py` | ✅ Working | List of positions |
| Asset allocation donut | `portfolio_analysis.py` | ✅ Working | By asset class |
| Date range filtering | `portfolio_analysis.py` | ✅ Working | 1M, 3M, 6M, YTD, 1Y, Max |
| Privacy mode (hide values) | `portfolio_analysis.py` | ✅ Working | Toggle to hide € amounts |
| Server-side caching | `tr_api.py` | ✅ Working | `~/.pytr/portfolio_cache.json` |
| Browser-side caching | `tr_connector.py` | ✅ Working | localStorage for offline |
| Auto-reconnect with saved creds | `tr_connector.py` | ✅ Working | Encrypted in browser |
| Per-position price histories (Yahoo) | `tr_api.py` | ✅ Working | For asset class filtering |
| **Invested series calculation** | `tr_api.py` | ✅ Working | `_build_invested_series_from_transactions()` |
| **Delta loading (transactions)** | `tr_api.py` | ✅ Working | Only fetches new transactions since last sync |
| **Delta loading (Yahoo prices)** | `portfolio_history.py` | ✅ Working | Only fetches missing price dates |
| **Market value calculation (fallback)** | `tr_api.py` | ✅ Working | `_build_history_with_market_values()` when TR API fails |

### ⚠️ KNOWN LIMITATIONS

| Issue | Impact | Workaround |
|-------|--------|------------|
| TR `portfolioAggregateHistory` API fails for some accounts | No direct portfolio value history from TR | Fallback calculates market values from position histories |
| ~3% invested amount undercount | Historical P2P transfers (pre-2024) excluded | Acceptable for TWR accuracy |
| Crypto has no Yahoo prices | XF000* ISINs not supported | No price history for crypto positions |

### 🔲 PLANNED BUT NOT IMPLEMENTED

| Feature | Priority | Description |
|---------|----------|-------------|
| Provider-agnostic architecture | Low | Support Scalable Capital in future |

---

## 2. ARCHITECTURE

### 2.1 File Structure

```
components/
├── tr_api.py           # TR API client (WebSocket, auth, data fetching, cache management)
├── tr_connector.py     # Dash UI component for TR connection modal + callbacks
├── benchmark_data.py   # Benchmark data fetching and caching
├── portfolio_history.py # Yahoo Finance price fetching with delta loading
├── performance_calc.py  # TWR, drawdown calculations 
└── auth.py             # Credential encryption utilities

pages/
└── portfolio_analysis.py # Main portfolio page with all charts/tables/callbacks

docs/
├── SPECIFICATION.md     # THIS FILE - source of truth
├── portfolio_data_flows.md
├── portfolio_history_calculation.md
├── portfolio_valuation.md
└── tr_api_architecture.md
```

### 2.2 Cache Files (`~/.pytr/`)

| File | Contents | Written By | Read By |
|------|----------|------------|---------|
| `portfolio_cache.json` | Complete portfolio snapshot with all derived data | `tr_api.py` | `portfolio_analysis.py` |
| `transactions_cache.json` | Raw transaction history for delta loading | `tr_api.py` | `tr_api.py` |
| `instrument_cache.json` | ISIN → name/type/imageId mapping | `tr_api.py` | `tr_api.py` |
| `price_cache.json` | Yahoo Finance prices: `{isin: {date: price}}` | `portfolio_history.py` | `portfolio_history.py` |
| `isin_symbol_cache.json` | ISIN → Yahoo ticker mapping | `portfolio_history.py` | `portfolio_history.py` |
| `benchmark_cache.json` | Benchmark index prices | `benchmark_data.py` | `portfolio_analysis.py` |

### 2.3 Complete Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      USER CLICKS "SYNC" or "VERIFY"                         │
│  (tr_connector.py → handle_auth_flow callback)                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ tr_api.py: fetch_all_data()                                                 │
│                                                                             │
│  1. Connect to TR WebSocket (if not connected)                              │
│  2. Fetch compact_portfolio → positions with qty, avgBuyIn, netValue        │
│  3. Fetch cash balance                                                      │
│  4. Enrich positions with instrument names (cache miss only)                │
│  5. Fetch timeline_transactions WITH DELTA LOADING:                         │
│     - Load transactions_cache.json                                          │
│     - Fetch from TR until hitting a cached transaction ID                   │
│     - Merge new + cached transactions                                       │
│     - Save updated transactions_cache.json                                  │
│  6. Build invested_series from transactions (deposits/withdrawals)          │
│  7. Fetch Yahoo prices for all positions WITH DELTA LOADING:                │
│     - Check price_cache.json for existing dates                             │
│     - Only fetch missing date ranges from Yahoo                             │
│     - Save updated price_cache.json                                         │
│  8. Try TR portfolioAggregateHistory API:                                   │
│     - If SUCCESS: merge with invested_series for correct invested values    │
│     - If FAILS: calculate market values from position histories             │
│  9. Pre-calculate TWR & drawdown series (cachedSeries)                      │
│ 10. Save complete result to portfolio_cache.json                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ tr_connector.py: Callback writes to Dash Stores                             │
│                                                                             │
│  - Serializes result to JSON                                                │
│  - Writes to portfolio-data-store (browser localStorage)                    │
│  - Writes encrypted credentials to tr-encrypted-creds (for auto-reconnect)  │
│  - Triggers all dependent callbacks via Dash reactivity                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ portfolio_analysis.py: Render UI (multiple callbacks)                       │
│                                                                             │
│  update_metrics() → Portfolio Value, Invested, Profit cards                 │
│  update_chart()   → Uses cachedSeries for fast rendering:                   │
│                     - dates, values, invested, twr, drawdown pre-calculated │
│                     - If asset filter active: rebuild from positionHistories│
│  update_holdings() → Holdings table from positions array                    │
│  update_donut()    → Asset allocation from positions                        │
│  update_returns()  → 1M, 3M, YTD, Total from history                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.4 Dash Store Architecture

| Store ID | Storage Type | Location | Purpose |
|----------|--------------|----------|---------|
| `portfolio-data-store` | localStorage | Browser | Main portfolio data - survives refresh/close |
| `tr-encrypted-creds` | localStorage | Browser | Encrypted phone+PIN for auto-reconnect |
| `tr-session-data` | session | Browser | Current connection state |
| `tr-auth-step` | memory | Browser | Authentication flow state |
| `selected-range` | memory | Browser | Current chart range (1m, 3m, etc.) |
| `privacy-mode` | memory | Browser | Hide sensitive values toggle |

**Data Flow for Page Load:**
```
1. Browser loads page /compare
2. Dash hydrates dcc.Store from localStorage
3. portfolio-data-store.data → update_metrics(), update_chart(), etc.
4. If no data: Show "Connect to Trade Republic" prompt
5. If has tr-encrypted-creds: Can auto-reconnect on user action
```

### 2.5 portfolio_cache.json Structure

```json
{
  "success": true,
  "cached_at": "2026-01-30T12:00:00",
  "data": {
    "totalValue": 862620.02,
    "investedAmount": 777080.94,
    "cash": 66396.26,
    "totalProfit": 85539.08,
    "totalProfitPercent": 11.01,
    
    "positions": [
      {
        "isin": "IE00B5BMR087",
        "name": "iShares Core S&P 500",
        "quantity": 150.5,
        "averageBuyIn": 450.00,
        "invested": 67725.00,
        "value": 75250.00,
        "profit": 7525.00,
        "instrumentType": "fund",
        "imageId": "..."
      }
    ],
    
    "transactions": [
      {
        "id": "abc123",
        "timestamp": "2025-03-15T10:30:00.000Z",
        "title": "Einzahlung",
        "subtitle": "Fertig",
        "amount": 1000.0,
        "eventType": "PAYMENT_INBOUND",
        "icon": "logos/IE00B5BMR087/v2"
      }
    ],
    
    "history": [
      {"date": "2024-01-15", "invested": 480000.00, "value": 520000.00},
      {"date": "2024-01-16", "invested": 480000.00, "value": 522000.00}
    ],
    
    "positionHistories": {
      "IE00B5BMR087": {
        "history": [{"date": "2024-01-15", "price": 450.00}],
        "quantity": 150.5,
        "instrumentType": "fund",
        "name": "iShares Core S&P 500"
      }
    },
    
    "cachedSeries": {
      "dates": ["2024-01-15", "2024-01-16"],
      "values": [520000.00, 522000.00],
      "invested": [480000.00, 480000.00],
      "twr": [0.0, 0.38],
      "drawdown": [0.0, 0.0]
    }
  }
}
```

---

## 3. KEY ALGORITHMS

### 3.1 Invested Series Calculation

**File:** `tr_api.py` → `_build_invested_series_from_transactions()`

**CAPITAL INFLOWS (positive):**
- `title='Einzahlung'` with amount > 0 → Bank deposit
- `subtitle='Fertig'` with amount > 0 → Completed P2P transfer

**CAPITAL OUTFLOWS (negative):**
- `subtitle='Gesendet'` with amount < 0 → Withdrawal

**NOT COUNTED:**
- Dividends, interest (returns, not capital)
- Buy/sell orders (internal movements)
- Rejected transfers, tax corrections

### 3.2 Market Value Calculation (Fallback)

**File:** `tr_api.py` → `_build_history_with_market_values()`

When TR's `portfolioAggregateHistory` API fails (common for some accounts):

1. Track holdings over time from buy/sell transactions
2. For each historical date:
   - Get cumulative invested from deposits
   - Calculate: `value = sum(position_cost_basis × price_ratio)`
   - Where `price_ratio = current_price / baseline_price`
3. Result: Different invested vs value (showing actual gains/losses)

### 3.3 Delta Loading (Transactions)

**File:** `tr_api.py` → `_fetch_timeline_transactions(delta_load=True)`

1. Load cached transaction IDs from `transactions_cache.json`
2. Fetch from TR API page by page
3. Stop when hitting a transaction ID already in cache
4. Merge: new transactions + cached transactions
5. Deduplicate by ID, sort by timestamp

### 3.4 Delta Loading (Prices)

**File:** `portfolio_history.py` → `get_prices_for_dates()`

1. Check `price_cache.json` for existing prices
2. Identify missing dates
3. Group missing dates into ranges (max 30-day gaps)
4. Fetch only missing ranges from Yahoo Finance
5. Update cache with new prices

---

## 4. KNOWN ISSUES & GOTCHAS

### 4.1 TR API Quirks

1. **`portfolioAggregateHistory` fails for some accounts** - Error: "Unknown topic type"
2. **`compact_portfolio` returns `netValue=0`** for most positions - Must calculate
3. **Transactions use `title`/`subtitle` not `type`** - German field names
4. **Timestamps are ISO format** - `2025-03-15T10:30:00.000Z`

### 4.2 Dash Callback Rules

1. **Output count must match** - Every return path needs same number of values
2. **`prevent_initial_call=True`** - Callback won't fire on page load
3. **`allow_duplicate=True`** - Needed when multiple callbacks write same output
4. **`no_update`** - Skip updating a specific output

### 4.3 Caching Layers

```
Layer 1: Browser localStorage (portfolio-data-store)
         └─ Fastest, survives refresh, used for immediate display
         
Layer 2: Server cache (~/.pytr/portfolio_cache.json)  
         └─ Pre-calculated series, shared across sessions
         
Layer 3: Granular caches (~/.pytr/price_cache.json, etc.)
         └─ Delta loading, avoids redundant API calls
```

---

## 5. CHANGE LOG

| Date | Change | Files |
|------|--------|-------|
| 2026-01-30 | Added market value calculation when TR API fails | `tr_api.py` |
| 2026-01-30 | Added delta loading for transactions | `tr_api.py` |
| 2026-01-30 | Improved delta loading logging for prices | `portfolio_history.py` |
| 2026-01-30 | Updated SPECIFICATION with complete data flow | `docs/SPECIFICATION.md` |
| 2026-01-27 | Fixed invested calculation - conservative method | `tr_api.py` |
| 2026-01-26 | Added invested series merge | `tr_api.py` |
| 2026-01-26 | Created this specification | `docs/SPECIFICATION.md` |
        "amount": 1000.0,
        "eventType": "PAYMENT_INBOUND"
      }
    ],
    "history": [
      {"date": "2024-01-15", "value": 500000.00, "invested": 480000.00}
    ],
    "positionHistories": {
      "IE00B5BMR087": [
        {"date": "2024-01-15", "price": 450.00}
      ]
    },
    "cachedSeries": {
      "dates": ["2024-01-15", "2024-01-16"],
      "values": [500000.00, 502000.00],
      "invested": [480000.00, 480000.00],
      "twr": [0.0, 0.4],
      "drawdown": [0.0, 0.0]
    }
  }
}
```

### 2.4 TR Transaction Types

**CAPITAL INFLOWS (count as positive invested):**

| Title | Subtitle | Amount | Description | Count as Invested? |
|-------|----------|--------|-------------|-------------------|
| `Einzahlung` | (any or empty) | > 0 | Bank deposit via SEPA | ✅ YES |
| (any person name) | `Fertig` | > 0 | Completed P2P transfer | ✅ YES |

**CAPITAL OUTFLOWS (count as negative invested):**

| Title | Subtitle | Amount | Description | Count as Invested? |
|-------|----------|--------|-------------|-------------------|
| (any) | `Gesendet` | < 0 | Withdrawal to bank/person | ✅ YES (negative) |

**NOT COUNTED (internal movements or returns):**

| Title | Subtitle | Amount | Type | Reason Excluded |
|-------|----------|--------|------|-----------------|
| `Zinsen` | (any) | > 0 | Interest | Return on investment |
| `Steuerkorrektur` | (any) | > 0 | Tax correction | Not capital flow |
| (any) | `Bardividende` | > 0 | Cash dividend | Return on investment |
| (any) | `Dividende` | > 0 | Reinvested dividend | Return on investment |
| (any) | `Kauforder` | < 0 | Buy order | Internal movement |
| (any) | `Verkaufsorder` | > 0 | Sell order | Internal movement |
| (any) | `Sparplan ausgeführt` | < 0 | Savings plan | Internal movement |
| (any) | `Abgelehnt` | any | Rejected transfer | Never completed |
| (any) | `% p.a.` patterns | > 0 | Interest rate payments | Return on investment |
| (any person name) | (empty) | any | Old P2P format | Excluded for reliability* |

*Note on old P2P transfers: TR's historical P2P transfers (before ~2024) used a format with empty subtitle.
These are excluded because they mix incoming/outgoing and have inconsistent data. This results in ~3%
undercount for users with significant historical P2P activity, which is acceptable for TWR calculations.

### 2.5 Invested Calculation Accuracy

The `_build_invested_series_from_transactions()` function achieves approximately **97% accuracy**
compared to TR's reported investedAmount:

```
Calculated: 774,436.00 EUR
TR Reports: 799,088.74 EUR
Accuracy:   96.9%
```

The ~3% gap comes from historical P2P transfers (pre-2024) that used an old format without the
`Fertig` subtitle. These are deliberately excluded because:

1. **Reliability**: Old P2P format doesn't distinguish incoming vs outgoing reliably
2. **Consistency**: Including them causes overcounting (~105% accuracy)
3. **Acceptable Error**: 3% undercount is better than 5% overcount for TWR
4. **Generic Solution**: Works for all users, not just specific accounts

---

## 3. IMPLEMENTATION CHECKLIST

Before ANY code change, verify:

- [ ] Feature is listed in this spec
- [ ] Architecture impact is understood
- [ ] All affected files are identified
- [ ] Changes maintain backward compatibility

After ANY code change, verify:

- [ ] `python -c "from components.tr_api import fetch_all_data; print('OK')"` works
- [ ] `python -c "from components.tr_connector import create_tr_connector_card; print('OK')"` works  
- [ ] `python -c "from pages.portfolio_analysis import layout; print('OK')"` works
- [ ] TR authentication still works (if auth code touched)
- [ ] Charts render correctly (if chart code touched)
- [ ] Update this spec with any new features/changes

---

## 4. KNOWN ISSUES & GOTCHAS

### 4.1 TR API Quirks

1. **`portfolioAggregateHistory` returns bad `invested` values** - Often 0 or same as value
2. **`compact_portfolio` returns `netValue=0`** for most positions - Must calculate from qty × price
3. **Transactions use `title`/`subtitle` not `type`** - e.g., `title='Einzahlung'` for deposits
4. **Timestamps are ISO format** - `2025-03-15T10:30:00.000Z`, extract date with `[:10]`

### 4.2 Dash Callback Rules

1. **Output count must match** - Every return path must have same number of values
2. **`prevent_initial_call=True`** - Callback won't fire on page load
3. **`allow_duplicate=True`** - Needed when multiple callbacks write same output
4. **`no_update`** - Use to skip updating a specific output

### 4.3 Caching

1. **Two caches exist** - Server (`~/.pytr/`) and Browser (localStorage)
2. **Browser takes precedence** - For immediate display
3. **Server cache has pre-calculated series** - TWR, drawdown ready to use
4. **Clear both to force full refresh** - Delete file AND click Disconnect

---

## 5. CHANGE LOG

| Date | Change | Files | Commit |
|------|--------|-------|--------|
| 2026-01-27 | Fixed invested calculation - conservative method at 97% accuracy | `tr_api.py` | pending |
| 2026-01-27 | Updated spec with TR transaction type analysis | `docs/SPECIFICATION.md` | pending |
| 2026-01-26 | Added invested series merge to fix Value chart | `tr_api.py` | pending |
| 2026-01-26 | Created this specification | `docs/SPECIFICATION.md` | pending |
| 2026-01-26 | Reverted broken modal UX changes | `tr_connector.py` | reverted |

