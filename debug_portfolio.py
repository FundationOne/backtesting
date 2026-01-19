import json
from pathlib import Path

cache = json.loads((Path.home() / '.pytr' / 'portfolio_cache.json').read_text())
data = cache.get('data', {})
positions = data.get('positions', [])

print('=== PORTFOLIO SUMMARY ===')
print(f'Total Value (stored): {data.get("totalValue", 0):,.2f}')
print(f'Cash: {data.get("cash", 0):,.2f}')
print(f'Positions: {len(positions)}')
print()

print('=== TOP 10 BY VALUE ===')
for p in sorted(positions, key=lambda x: x.get('value', 0), reverse=True)[:10]:
    name = p.get('name', 'Unknown')[:30]
    qty = p.get('quantity', 0)
    avg_buy = p.get('averageBuyIn', 0)
    invested = p.get('invested', 0)
    value = p.get('value', 0)
    current_price = p.get('currentPrice', 0)
    isin = p.get('isin', '')
    print(f'{name} ({isin})')
    print(f'  qty={qty:.4f}, avg_buy={avg_buy:.2f}, current_price={current_price:.2f}')
    print(f'  invested={invested:,.0f}, value={value:,.0f}, ratio={value/invested if invested > 0 else 0:.2f}x')
    print()

print('=== SUM CHECK ===')
total_invested = sum(p.get('invested', 0) for p in positions)
total_value = sum(p.get('value', 0) for p in positions)
print(f'Sum of invested: {total_invested:,.2f}')
print(f'Sum of values: {total_value:,.2f}')
