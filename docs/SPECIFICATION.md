# Portfolio Calculation Spec (Compact)

## Source of Truth
- **Share quantities**: TR `timeline_detail_v2` per transaction
- **Current positions**: TR `compact_portfolio`  
- **Prices**: Yahoo Finance
- **Invested**: Deposits - Withdrawals only

## Calculation Flow
```
1. Fetch positions (TR compact_portfolio) → current qty per ISIN
2. Fetch transactions (TR timeline_transactions) → list of buys/sells/deposits
3. Enrich trades (TR timeline_detail_v2) → get shares for each buy/sell
4. VALIDATE: compare calculated vs actual shares
5. Build holdings timeline → walk forward, accumulate shares
6. Fetch prices (Yahoo) → price per ISIN per date
7. Calculate values → qty × price for each date
8. Build invested series → cumulative deposits
9. Combine → history with (date, invested, value)
```

## Key Rules
- Shares from TR, NEVER calculate from amount/price
- Walk FORWARD from empty holdings
- History starts from first deposit date
- Today's value = TR current_total

## Transaction Types
**Buys** (add shares): Kauforder, Sparplan ausgeführt, Limit-Buy-Order, Bonusaktien, Aktiensplit  
**Sells** (remove shares): Verkaufsorder, Limit-Sell-Order, Stop-Sell-Order  
**Deposits** (add invested): Einzahlung, subtitle='Fertig'  
**Withdrawals** (subtract invested): subtitle='Gesendet'

## Enrichment Rules
Re-enrich transaction if:
- `shares` is None or 0
- `shares` > 1,000,000 (likely parse error)

Robustness:
- 2 retries per API call with backoff
- Rate limit: 0.1s pause every 10 requests
- Longer pause (1s) after 5 consecutive failures

## Validation (after sync)
- Count trades with/without shares
- Compare calculated vs actual qty per ISIN
- Log warnings if >20% trades missing shares
- Log warnings if >30% positions mismatched

## Cache Files (~/.pytr/)
| File | Content | On Sync |
|------|---------|---------|
| transactions_cache.json | All transactions with shares | Merged |
| portfolio_cache.json | Final result | Overwritten |
| price_cache.json | Yahoo prices | Delta merged |

## Known Issues
- TR `portfolioAggregateHistory` fails → use fallback
- Crypto has no Yahoo prices
- German number format: "7,470352" = 7.470352 shares

## Diagnostic
Run `python tools/trace_asset.py` to verify any ISIN end-to-end.

