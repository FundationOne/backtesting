"""
Trade Republic API Wrapper
Uses pytr library for actual TR API communication
"""

import asyncio
from datetime import datetime, timedelta
import os
import json
import base64
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError

# Minimum seconds between Trade Republic syncs.
# Keeps the app responsive and prevents accidental rapid re-syncs.
MIN_SYNC_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours

# pytr imports
from pytr.api import TradeRepublicApi
from pytr.utils import get_logger

# Setup logging
log = get_logger(__name__)

# Credentials storage path (server-side for keyfile only)
TR_CREDENTIALS_DIR = Path.home() / ".pytr"
TR_KEYFILE = TR_CREDENTIALS_DIR / "keyfile.pem"
TR_TRANSACTIONS_CACHE = TR_CREDENTIALS_DIR / "transactions_cache.json"

# Encryption key from environment (set this in your .env or hosting config)
ENCRYPTION_KEY = os.environ.get("TR_ENCRYPTION_KEY", "default-dev-key-change-in-prod")


def _get_cipher_key():
    """Derive a 32-byte key from the encryption key."""
    return hashlib.sha256(ENCRYPTION_KEY.encode()).digest()


def encrypt_credentials(phone_no: str, pin: str) -> str:
    """Encrypt credentials for browser storage."""
    try:
        from cryptography.fernet import Fernet
        # Derive Fernet key from our encryption key
        key = base64.urlsafe_b64encode(_get_cipher_key())
        f = Fernet(key)
        data = json.dumps({"phone": phone_no, "pin": pin})
        encrypted = f.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    except ImportError:
        # Fallback: simple XOR obfuscation (install cryptography for better security)
        data = json.dumps({"phone": phone_no, "pin": pin})
        key = _get_cipher_key()
        encrypted = bytes([data.encode()[i] ^ key[i % len(key)] for i in range(len(data))])
        return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_credentials(encrypted: str) -> Tuple[Optional[str], Optional[str]]:
    """Decrypt credentials from browser storage."""
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(_get_cipher_key())
        f = Fernet(key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted.encode())
        decrypted = f.decrypt(encrypted_bytes).decode()
        data = json.loads(decrypted)
        return data.get("phone"), data.get("pin")
    except ImportError:
        # Fallback XOR
        encrypted_bytes = base64.urlsafe_b64decode(encrypted.encode())
        key = _get_cipher_key()
        decrypted = bytes([encrypted_bytes[i] ^ key[i % len(key)] for i in range(len(encrypted_bytes))])
        data = json.loads(decrypted.decode())
        return data.get("phone"), data.get("pin")
    except Exception as e:
        log.error(f"Failed to decrypt credentials: {e}")
        return None, None


class TRConnection:
    """Manages Trade Republic connection state."""
    
    def __init__(self):
        self.api: Optional[TradeRepublicApi] = None
        self.phone_no: Optional[str] = None
        self.pin: Optional[str] = None
        self.is_connected = False
        self.portfolio_data: Optional[Dict] = None
        self.cash_data: Optional[Dict] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()
        self._op_lock = threading.Lock()

        self._instrument_cache_path = TR_CREDENTIALS_DIR / "instrument_cache.json"

    def _ensure_worker_loop(self) -> asyncio.AbstractEventLoop:
        """Ensure a single dedicated asyncio loop exists for all pytr websocket work.

        Dash callbacks can run in different threads; mixing event loops causes
        'Future attached to a different loop' runtime errors.
        """
        if self._loop and self._thread and self._thread.is_alive():
            return self._loop

        self._loop_ready.clear()

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._loop_ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_runner, name="tr-async-loop", daemon=True)
        self._thread.start()
        if not self._loop_ready.wait(timeout=5):
            raise RuntimeError("Failed to start TR asyncio loop thread")
        if not self._loop:
            raise RuntimeError("TR asyncio loop not initialized")
        return self._loop

    def run(self, coro, timeout: float = 90):
        """Run a coroutine on the dedicated TR loop and wait for its result."""
        loop = self._ensure_worker_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeoutError:
            fut.cancel()
            raise

    def run_serialized(self, coro, timeout: float = 90):
        """Run a coroutine while holding an operation lock.

        This prevents overlapping websocket recv/unsubscribe calls from multiple Dash callbacks.
        """
        with self._op_lock:
            return self.run(coro, timeout=timeout)

    def has_credentials(self) -> bool:
        """Best-effort check for a reusable TR session (keyfile)."""
        return TR_KEYFILE.exists()

    def _load_instrument_cache(self) -> Dict[str, str]:
        try:
            if self._instrument_cache_path.exists():
                data = json.loads(self._instrument_cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # values should be shortName/name strings
                    return {str(k): str(v) for k, v in data.items() if k and v}
        except Exception as e:
            log.warning(f"Failed to load instrument cache: {e}")
        return {}

    def _save_instrument_cache(self, cache: Dict[str, str]) -> None:
        try:
            TR_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            self._instrument_cache_path.write_text(json.dumps(cache), encoding="utf-8")
        except Exception as e:
            log.warning(f"Failed to save instrument cache: {e}")

    def _load_transactions_cache(self) -> List[Dict]:
        """Load cached transactions."""
        try:
            if TR_TRANSACTIONS_CACHE.exists():
                data = json.loads(TR_TRANSACTIONS_CACHE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
        except Exception as e:
            log.warning(f"Failed to load transactions cache: {e}")
        return []

    def _save_transactions_cache(self, transactions: List[Dict]) -> None:
        """Save transactions to cache."""
        try:
            TR_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            TR_TRANSACTIONS_CACHE.write_text(json.dumps(transactions, default=str), encoding="utf-8")
            log.info(f"Saved {len(transactions)} transactions to cache")
        except Exception as e:
            log.warning(f"Failed to save transactions cache: {e}")

    async def _fetch_timeline_transactions(self, delta_load: bool = True) -> List[Dict]:
        """Fetch timeline transactions from TR with delta loading.
        
        Delta loading: Only fetches new transactions since the last sync.
        This significantly speeds up subsequent syncs.
        
        Args:
            delta_load: If True, stop when we hit a transaction already in cache.
                       If False, fetch all transactions from scratch.
        
        Returns:
            Complete list of transactions (new + cached)
        """
        if not self.api or not self.is_connected:
            log.error("Cannot fetch timeline - not connected")
            return []
        
        # Load cached transactions for delta comparison
        cached_txns = self._load_transactions_cache() if delta_load else []
        cached_ids = {txn.get('id') for txn in cached_txns if txn.get('id')}
        
        if cached_txns and delta_load:
            log.info(f"Delta loading: {len(cached_txns)} transactions in cache")
        
        new_transactions = []
        after_cursor = None
        page = 0
        max_pages = 100  # Safety limit
        found_cached = False
        
        log.info("Fetching timeline transactions...")
        
        while page < max_pages:
            page += 1
            try:
                # Subscribe to timeline transactions
                await self.api.timeline_transactions(after=after_cursor)
                sub_id, sub_params, response = await self.api.recv()
                await self.api.unsubscribe(sub_id)
                
                items = response.get('items', [])
                if not items:
                    log.info(f"Timeline page {page}: no more items")
                    break
                    
                page_new_count = 0
                for item in items:
                    item_id = item.get('id')
                    
                    # Delta loading: stop if we hit a cached transaction
                    if delta_load and item_id in cached_ids:
                        found_cached = True
                        log.info(f"Timeline page {page}: found cached transaction, stopping delta load")
                        break
                    
                    # Extract basic transaction info
                    txn = {
                        'id': item_id,
                        'timestamp': item.get('timestamp'),
                        'title': item.get('title'),
                        'subtitle': item.get('subtitle'),
                        'eventType': item.get('eventType'),
                        'amount': item.get('amount', {}).get('value'),
                        'currency': item.get('amount', {}).get('currency'),
                        'icon': item.get('icon'),
                    }
                    new_transactions.append(txn)
                    page_new_count += 1
                
                if found_cached:
                    break
                    
                log.info(f"Timeline page {page}: got {page_new_count} new items")
                
                # Check for next page
                cursors = response.get('cursors', {})
                after_cursor = cursors.get('after')
                if not after_cursor:
                    log.info(f"Timeline complete after {page} pages")
                    break
                    
            except Exception as e:
                log.error(f"Error fetching timeline page {page}: {e}")
                break
        
        # Merge new transactions with cached ones
        if delta_load and cached_txns and new_transactions:
            # New transactions are newer, so prepend them
            all_transactions = new_transactions + cached_txns
            log.info(f"Delta load complete: {len(new_transactions)} new + {len(cached_txns)} cached = {len(all_transactions)} total")
        elif delta_load and cached_txns and not new_transactions:
            all_transactions = cached_txns
            log.info(f"Delta load: No new transactions, using {len(cached_txns)} cached")
        else:
            all_transactions = new_transactions
            log.info(f"Full load: {len(all_transactions)} transactions")
        
        # Sort by timestamp descending (newest first) and deduplicate
        seen_ids = set()
        unique_transactions = []
        for txn in sorted(all_transactions, key=lambda x: x.get('timestamp', ''), reverse=True):
            txn_id = txn.get('id')
            if txn_id and txn_id not in seen_ids:
                seen_ids.add(txn_id)
                unique_transactions.append(txn)
        
        return unique_transactions

    async def _fetch_portfolio_aggregate_history(self, timeframe: str = "max") -> List[Dict]:
        """Fetch aggregate portfolio history from TR.
        
        Uses the portfolioAggregateHistory API to get real portfolio value over time.
        Timeframe options: 1d, 1w, 1m, 3m, 1y, max
        """
        if not self.api or not self.is_connected:
            log.error("Cannot fetch portfolio history - not connected")
            return []
        
        try:
            log.info(f"Fetching portfolio aggregate history (timeframe={timeframe})...")
            await self.api.portfolio_history(timeframe)
            sub_id, sub_params, response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            # Response should contain historical data points
            # Expected format: {aggregates: [{time, value, invested}, ...]}
            aggregates = response.get('aggregates', [])
            log.info(f"Got {len(aggregates)} aggregate history points")
            
            history = []
            for agg in aggregates:
                ts = agg.get('time', agg.get('timestamp', ''))
                if ts:
                    # Convert timestamp to date string
                    date_str = ts[:10] if len(ts) >= 10 else ts
                    history.append({
                        'date': date_str,
                        'value': float(agg.get('close', agg.get('value', 0))),
                        'invested': float(agg.get('invested', agg.get('averageBuyIn', 0))),
                    })
            
            return history
        except Exception as e:
            log.error(f"Error fetching portfolio history: {e}")
            return []

    async def _fetch_position_history(self, isin: str, timeframe: str = "max") -> List[Dict]:
        """Fetch price history for a single position/instrument.
        
        Uses the aggregateHistory API to get historical prices for an ISIN.
        NOTE: This is unreliable - many instruments fail. Use _build_position_histories_from_yahoo instead.
        """
        if not self.api or not self.is_connected:
            log.error("Cannot fetch position history - not connected")
            return []
        
        try:
            log.info(f"Fetching history for {isin}...")
            await self.api.performance_history(isin, timeframe, exchange="LSX")
            sub_id, sub_params, response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            aggregates = response.get('aggregates', response.get('expectedHistoryLight', []))
            log.info(f"Got {len(aggregates)} history points for {isin}")
            
            history = []
            for agg in aggregates:
                ts = agg.get('time', agg.get('date', ''))
                if ts:
                    date_str = ts[:10] if len(ts) >= 10 else ts
                    # Price data - close price
                    close_price = float(agg.get('close', agg.get('price', 0)))
                    history.append({
                        'date': date_str,
                        'price': close_price,
                    })
            
            return history
        except Exception as e:
            log.error(f"Error fetching history for {isin}: {e}")
            return []

    def _build_position_histories_from_yahoo(
        self, transactions: List[Dict], positions: List[Dict]
    ) -> Dict[str, Dict]:
        """Build per-position price histories using Yahoo Finance.
        
        This is more reliable than TR's performance_history API which fails for many instruments.
        Uses the same approach as portfolio_history.py but integrated into TR sync.
        
        Returns:
            Dict of {isin: {history: [{date, price}], quantity, instrumentType, name}}
        """
        from components.portfolio_history import (
            extract_isin_from_icon,
            get_prices_for_dates,
        )
        
        # Build position lookup
        pos_lookup = {p.get('isin', ''): p for p in positions}
        isin_to_name = {p.get('isin', ''): p.get('name', '') for p in positions}
        
        # Buy/sell transaction subtitles (German)
        BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
        SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
        
        # Find all ISINs that have transactions
        isins_with_transactions = set()
        all_dates = set()
        
        for txn in transactions:
            subtitle = txn.get("subtitle", "")
            icon = txn.get("icon", "")
            timestamp = txn.get("timestamp", "")
            
            if not timestamp:
                continue
            
            isin = extract_isin_from_icon(icon)
            if not isin:
                continue
            
            if subtitle in BUY_SUBTITLES or subtitle in SELL_SUBTITLES:
                isins_with_transactions.add(isin)
                try:
                    date = datetime.fromisoformat(timestamp.replace("+0000", "+00:00")).replace(tzinfo=None)
                    all_dates.add(date.date())
                except:
                    pass
        
        if not isins_with_transactions or not all_dates:
            return {}
        
        # Generate history dates (monthly + transaction dates + today)
        start_date = min(all_dates)
        end_date = datetime.now().date()
        
        history_dates = set()
        current = start_date.replace(day=1)
        while current <= end_date:
            history_dates.add(current)
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        history_dates.update(all_dates)
        history_dates.add(end_date)
        sorted_dates = sorted(history_dates)
        
        # Fetch prices for each ISIN
        position_histories = {}
        
        for idx, isin in enumerate(isins_with_transactions):
            name = isin_to_name.get(isin, isin)
            pos = pos_lookup.get(isin, {})
            
            log.info(f"[{idx+1}/{len(isins_with_transactions)}] Fetching prices for {name}...")
            
            dates_as_dt = [datetime.combine(d, datetime.min.time()) for d in sorted_dates]
            prices = get_prices_for_dates(isin, name, dates_as_dt)
            
            if prices:
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
                        'name': name,
                    }
            else:
                log.warning(f"  No prices available for {name}")
        
        return position_histories

    def _build_history_with_market_values(
        self, 
        transactions: List[Dict], 
        position_histories: Dict[str, Dict],
        invested_series: Dict[str, float],
        current_total: float
    ) -> List[Dict]:
        """Build portfolio history with actual market values from position price histories.
        
        This method calculates:
        - invested: cumulative capital deposited (from invested_series)
        - value: sum of (holdings × price) for each position at each date
        
        The key insight is tracking holdings changes over time:
        - Buy transactions increase holdings
        - Sell transactions decrease holdings
        - Market value = holdings × current price
        
        Args:
            transactions: All timeline transactions
            position_histories: {isin: {history: [{date, price}], ...}} from Yahoo
            invested_series: {date: cumulative_invested} from deposits
            current_total: Current live portfolio value
            
        Returns:
            List of {date, invested, value} dicts
        """
        from components.portfolio_history import extract_isin_from_icon
        
        if not position_histories or not transactions:
            log.warning("No position histories or transactions - cannot calculate market values")
            return self._build_history_from_transactions(transactions, current_total)
        
        # Buy/sell transaction subtitles (German)
        BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
        SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
        
        # Track holdings changes: {isin: [(date_str, cost_change)]}
        # Positive = buy, negative = sell
        holdings_changes: Dict[str, List[Tuple[str, float]]] = {}
        
        for txn in transactions:
            subtitle = txn.get("subtitle", "")
            icon = txn.get("icon", "")
            amount = txn.get("amount")
            timestamp = txn.get("timestamp", "")
            
            if not timestamp or amount is None:
                continue
            
            date_str = timestamp[:10]  # YYYY-MM-DD
            isin = extract_isin_from_icon(icon)
            if not isin:
                continue
            
            cost = abs(float(amount))
            
            if subtitle in BUY_SUBTITLES:
                holdings_changes.setdefault(isin, []).append((date_str, cost))
            elif subtitle in SELL_SUBTITLES:
                holdings_changes.setdefault(isin, []).append((date_str, -cost))
        
        # Build price lookup: {isin: {date_str: price}}
        price_lookup: Dict[str, Dict[str, float]] = {}
        for isin, data in position_histories.items():
            price_lookup[isin] = {}
            for point in data.get('history', []):
                price_lookup[isin][point['date']] = point['price']
        
        # Get all dates we need (union of invested_series dates and price dates)
        all_dates = set(invested_series.keys())
        for isin_prices in price_lookup.values():
            all_dates.update(isin_prices.keys())
        
        # Add today
        today = datetime.now().strftime('%Y-%m-%d')
        all_dates.add(today)
        
        sorted_dates = sorted(all_dates)
        
        if not sorted_dates:
            return self._build_history_from_transactions(transactions, current_total)
        
        # Build cumulative holdings at each date (by cost basis)
        # holdings_at_date[isin][date] = cumulative cost basis
        holdings_at_date: Dict[str, Dict[str, float]] = {}
        
        for isin, changes in holdings_changes.items():
            holdings_at_date[isin] = {}
            sorted_changes = sorted(changes, key=lambda x: x[0])
            cumulative = 0.0
            
            for date_str, cost_change in sorted_changes:
                cumulative += cost_change
                cumulative = max(0, cumulative)  # Can't go negative
                holdings_at_date[isin][date_str] = cumulative
        
        # Now build history with actual values
        history = []
        
        for date_str in sorted_dates:
            # Get invested amount (use last known value <= this date)
            invested = 0.0
            for inv_date in sorted(invested_series.keys()):
                if inv_date <= date_str:
                    invested = invested_series[inv_date]
                else:
                    break
            
            # Calculate market value
            total_value = 0.0
            
            for isin in holdings_at_date.keys():
                # Get holdings at this date (last known value)
                cost_basis = 0.0
                for hold_date in sorted(holdings_at_date[isin].keys()):
                    if hold_date <= date_str:
                        cost_basis = holdings_at_date[isin][hold_date]
                    else:
                        break
                
                if cost_basis <= 0:
                    continue
                
                # Get price at this date (or nearest earlier date)
                prices = price_lookup.get(isin, {})
                price = None
                first_price = None
                first_price_date = None
                
                for p_date in sorted(prices.keys()):
                    if first_price is None:
                        first_price = prices[p_date]
                        first_price_date = p_date
                    if p_date <= date_str:
                        price = prices[p_date]
                    else:
                        break
                
                if price and first_price and first_price > 0:
                    # Get the first price on or after the first holding date
                    first_hold_date = min(holdings_at_date[isin].keys()) if holdings_at_date[isin] else None
                    if first_hold_date:
                        baseline_price = first_price
                        for p_date in sorted(prices.keys()):
                            if p_date >= first_hold_date:
                                baseline_price = prices[p_date]
                                break
                        
                        if baseline_price > 0:
                            # Calculate value using price ratio
                            # This accounts for positions bought at different times
                            growth = price / baseline_price
                            position_value = cost_basis * growth
                            total_value += position_value
                        else:
                            total_value += cost_basis
                    else:
                        total_value += cost_basis
                else:
                    # No price - use cost basis
                    total_value += cost_basis
            
            # Only add if we have meaningful data
            if invested > 0 or total_value > 0:
                history.append({
                    'date': date_str,
                    'invested': round(invested, 2),
                    'value': round(total_value, 2) if total_value > 0 else round(invested, 2),
                })
        
        # Ensure today has the live current_total value
        if history and history[-1]['date'] == today:
            history[-1]['value'] = round(current_total, 2)
        elif history:
            history.append({
                'date': today,
                'invested': history[-1]['invested'],
                'value': round(current_total, 2),
            })
        
        log.info(f"Built history with market values: {len(history)} data points")
        
        # Debug: show sample
        if history:
            sample = history[:2] + history[-2:] if len(history) > 4 else history
            for h in sample:
                log.info(f"  History sample: {h['date']}: invested={h['invested']:,.2f}, value={h['value']:,.2f}")
        
        return history

    def _build_history_from_transactions(self, transactions: List[Dict], current_total: float) -> List[Dict]:
        """Build portfolio value history from transactions.
        
        Since TR doesn't provide historical portfolio values, we reconstruct them
        by tracking cash flows (deposits, withdrawals, interest, dividends) over time.
        
        Transaction types are identified by 'title' and 'subtitle' fields:
        - title='Einzahlung' (deposit) - positive cash inflow
        - title='Zinsen' (interest) - positive cash inflow  
        - subtitle='Fertig' with positive amount - completed transfer inflow
        - subtitle='Bardividende' or 'Dividende' - positive cash inflow
        - subtitle='Gesendet' with negative amount - outbound transfer
        """
        if not transactions:
            return []
        
        # Group cash inflows/outflows by date
        daily_flows: Dict[str, float] = {}
        
        for txn in transactions:
            ts = txn.get('timestamp', '')
            if not ts:
                continue
            
            date_str = ts[:10]  # YYYY-MM-DD
            title = txn.get('title', '') or ''
            subtitle = txn.get('subtitle', '') or ''
            amount = txn.get('amount')
            
            if amount is None:
                continue
            
            amount = float(amount)
            
            # Determine if this is a cash flow event
            flow = 0.0
            
            # Deposits - positive amounts with Einzahlung title
            if title == 'Einzahlung' and amount > 0:
                flow = amount
            # Completed transfers (deposits from bank) - subtitle='Fertig' with positive amount
            elif subtitle == 'Fertig' and amount > 0:
                flow = amount
            # Interest payments - positive amounts with Zinsen title
            elif title == 'Zinsen' and amount > 0:
                flow = amount
            # Dividends - check subtitle
            elif subtitle in {'Bardividende', 'Dividende'} and amount > 0:
                flow = amount
            # Withdrawals - 'Gesendet' (sent) with negative amounts
            elif subtitle == 'Gesendet' and amount < 0:
                flow = amount  # Already negative
            
            if flow != 0:
                daily_flows[date_str] = daily_flows.get(date_str, 0) + flow
        
        if not daily_flows:
            # No deposit/withdrawal transactions found, return minimal history
            log.warning("No cash flow transactions found - using minimal history")
            today = datetime.now().strftime('%Y-%m-%d')
            return [{'date': today, 'value': current_total}]
        
        # Sort dates ascending
        sorted_dates = sorted(daily_flows.keys())
        
        # Build history: start from first date and accumulate
        # We'll show cumulative cash inflows over time
        history = []
        cumulative = 0.0
        
        for date_str in sorted_dates:
            cumulative += daily_flows[date_str]
            history.append({
                'date': date_str,
                'invested': cumulative,
                'value': cumulative,  # We don't have market values, so use invested
            })
        
        # Add current value as latest point
        today = datetime.now().strftime('%Y-%m-%d')
        if not history or history[-1]['date'] != today:
            history.append({
                'date': today,
                'invested': cumulative,
                'value': current_total,
            })
        else:
            # Update today's value with actual current value
            history[-1]['value'] = current_total
        
        log.info(f"Built history with {len(history)} data points from {len(daily_flows)} cash flow days, total deposited: {cumulative:.2f}")
        
        return history
    
    def _build_invested_series_from_transactions(self, transactions: List[Dict]) -> Dict[str, float]:
        """Build a date -> cumulative invested amount mapping from transactions.
        
        This gives us accurate invested amounts at each date, computed from actual
        deposit/withdrawal transactions. TR's aggregate history often returns 0 or
        incorrect invested values, so we use this as the source of truth.
        
        CAPITAL INFLOWS (counted as positive):
        - Einzahlung: Bank deposits (title='Einzahlung', amount > 0)
        - Fertig transfers: Completed P2P incoming (subtitle='Fertig', amount > 0)
        
        CAPITAL OUTFLOWS (counted as negative):
        - Gesendet: Bank withdrawals (subtitle='Gesendet', amount < 0)
        
        NOT COUNTED as capital flows:
        - Dividends (Dividende, Bardividende) - returns on investment
        - Interest (Zinsen, Festzins, Zinszahlung) - returns
        - Tax corrections (Steuerkorrektur, Vorabpauschale)
        - Sales (Verkaufsorder, etc.) - internal portfolio movements
        - Purchases (Kauforder, Sparplan, etc.) - internal portfolio movements
        - Rejected transfers (Abgelehnt) - never completed
        - Old P2P with no subtitle - inconsistent historical data, excluded for reliability
        
        Note: This conservative approach captures ~97% of invested capital for most users.
        The ~3% gap may come from historical P2P transfers that used an old format without
        the 'Fertig' subtitle. This is acceptable for TWR calculation accuracy.
        
        Returns:
            Dict mapping date string (YYYY-MM-DD) to cumulative invested amount
        """
        if not transactions:
            return {}
        
        # Titles that represent system transactions, NOT capital flows
        # (even if they have no subtitle)
        non_capital_titles = {
            'Zinsen',           # Interest payments
            'Steuerkorrektur',  # Tax corrections
        }
        
        # Subtitles that are NOT capital flows
        non_capital_subtitles = {
            # Dividends and interest
            'Bardividende', 'Dividende', 
            'Festzins', 'Zinszahlung',
            # Internal portfolio operations
            'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order',
            'Kauforder', 'Limit-Buy-Order', 
            'Sparplan ausgeführt', 'Sparplan fehlgeschlagen',
            # Tax and adjustments
            'Vorabpauschale', 'Bonusaktien',
            # Failed/rejected transfers
            'Abgelehnt',
            # Corporate actions
            'Tausch', 'Fusion',
        }
        
        # Subtitles with variable suffixes (e.g., "2 % p.a.", "3,25 % p.a.")
        non_capital_subtitle_patterns = ['% p.a.', '1 % Bonus']
        
        # Build daily cash flows
        daily_flows = {}
        
        for txn in transactions:
            ts = txn.get('timestamp', '')
            if not ts:
                continue
            
            date_str = ts[:10]  # YYYY-MM-DD
            title = txn.get('title', '') or ''
            subtitle = txn.get('subtitle', '') or ''
            amount = txn.get('amount')
            
            if amount is None:
                continue
            
            amount = float(amount)
            flow = 0.0
            
            # Skip known non-capital titles
            if title in non_capital_titles:
                continue
            
            # Skip known non-capital subtitles
            if subtitle in non_capital_subtitles:
                continue
            
            # Skip pattern-based non-capital subtitles (interest rates, etc.)
            if any(pattern in subtitle for pattern in non_capital_subtitle_patterns):
                continue
            
            # === CAPITAL INFLOWS ===
            
            # 1. Bank deposits: title='Einzahlung', positive amount
            if title == 'Einzahlung' and amount > 0:
                flow = amount
            
            # 2. Completed P2P transfers: subtitle='Fertig', positive amount
            elif subtitle == 'Fertig' and amount > 0:
                flow = amount
            
            # === CAPITAL OUTFLOWS ===
            
            # 3. Bank withdrawals: subtitle='Gesendet', negative amount
            elif subtitle == 'Gesendet' and amount < 0:
                flow = amount  # Already negative
            
            # Note: We deliberately do NOT count old P2P transfers (no subtitle)
            # as they are inconsistent and lead to inaccurate calculations.
            # Users with significant historical P2P may see ~3% undercount.
            
            if flow != 0:
                daily_flows[date_str] = daily_flows.get(date_str, 0.0) + flow
        
        if not daily_flows:
            return {}
        
        # Sort dates and compute cumulative invested
        sorted_dates = sorted(daily_flows.keys())
        invested_series = {}
        cumulative = 0.0
        
        for date_str in sorted_dates:
            cumulative += daily_flows[date_str]
            invested_series[date_str] = cumulative
        
        log.info(f"Built invested series: {len(invested_series)} dates, "
                 f"final cumulative: {cumulative:,.2f} EUR")
        
        return invested_series
    
    def _merge_history_with_invested(self, history: List[Dict], invested_series: Dict[str, float]) -> List[Dict]:
        """Merge portfolio history with transaction-derived invested amounts.
        
        TR's aggregate history often returns incorrect invested values (0 or same as value).
        This function replaces those with accurate values computed from transactions.
        
        Args:
            history: List of {date, value, invested} from TR aggregate history
            invested_series: Dict mapping date -> cumulative invested from transactions
            
        Returns:
            History with corrected invested values
        """
        if not history or not invested_series:
            return history
        
        # Get sorted invested dates for interpolation
        invested_dates = sorted(invested_series.keys())
        if not invested_dates:
            return history
        
        # For each history point, find the most recent invested value
        for point in history:
            date_str = point.get('date', '')[:10]
            
            # Find most recent invested value on or before this date
            invested_value = None
            for inv_date in invested_dates:
                if inv_date <= date_str:
                    invested_value = invested_series[inv_date]
                else:
                    break
            
            # Only update if we found a value (keep original if before first transaction)
            if invested_value is not None:
                point['invested'] = invested_value
        
        return history
    
    def has_keyfile(self) -> bool:
        """Check if keyfile exists (needed for reconnect)."""
        return TR_KEYFILE.exists()
    
    def get_encrypted_credentials(self, phone_no: str, pin: str) -> str:
        """Encrypt credentials for browser storage."""
        return encrypt_credentials(phone_no, pin)
    
    def set_credentials_from_encrypted(self, encrypted: str) -> bool:
        """Set credentials from encrypted browser storage."""
        phone, pin = decrypt_credentials(encrypted)
        if phone and pin:
            self.phone_no = phone
            self.pin = pin
            return True
        return False
    
    def clear_credentials(self):
        """Clear credentials and keyfile."""
        if TR_KEYFILE.exists():
            TR_KEYFILE.unlink()
        self.phone_no = None
        self.pin = None
        self.is_connected = False
        self.api = None
    
    async def _initiate_web_login(self, phone_no: str, pin: str) -> Dict[str, Any]:
        """
        Initiate web login - this sends a 4-digit code to the TR app.
        Returns countdown seconds for verification step.
        """
        try:
            self.phone_no = phone_no
            self.pin = pin
            
            # Create API instance
            self.api = TradeRepublicApi(
                phone_no=phone_no,
                pin=pin,
                keyfile=str(TR_KEYFILE)
            )
            
            # Initiate web login (sends 4-digit code to app) - THIS IS SYNC, not async!
            countdown = self.api.initiate_weblogin()
            
            return {
                "success": True,
                "message": f"Verification code sent to your Trade Republic app (expires in {countdown}s)",
                "requires_code": True,
                "countdown": countdown
            }
        except Exception as e:
            log.error(f"Web login initiation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _complete_web_login(self, code: str) -> Dict[str, Any]:
        """
        Complete web login with the 4-digit verification code.
        Returns encrypted credentials for browser storage.
        """
        try:
            if not self.api:
                return {"success": False, "error": "No login in progress"}
            
            # Complete the web login with code - THIS IS SYNC, not async!
            self.api.complete_weblogin(code)
            
            self.is_connected = True
            
            # Return encrypted credentials for browser storage
            encrypted_creds = None
            if self.phone_no and self.pin:
                encrypted_creds = self.get_encrypted_credentials(self.phone_no, self.pin)
            
            return {
                "success": True,
                "message": "Successfully connected to Trade Republic",
                "encrypted_credentials": encrypted_creds
            }
        except Exception as e:
            log.error(f"Web login completion failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _fetch_portfolio(self) -> Dict[str, Any]:
        """Fetch portfolio data from TR."""
        try:
            if not self.api or not self.is_connected:
                return {"success": False, "error": "Not connected"}
            
            # Get compact portfolio (correct subscription type)
            # WebSocket connects automatically on first subscribe
            await self.api.compact_portfolio()
            sub_id, sub_params, portfolio_response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            log.info(f"Portfolio response: {portfolio_response}")
            
            # Get cash balance
            await self.api.cash()
            sub_id, sub_params, cash_response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            log.info(f"Cash response: {cash_response}")
            
            self.portfolio_data = portfolio_response
            self.cash_data = cash_response
            
            # Parse compact portfolio format
            # compactPortfolio returns: {netValue, positions: [{instrumentId, netSize, averageBuyIn, netValue}]}
            positions = portfolio_response.get('positions', [])
            net_value = portfolio_response.get('netValue', 0)
            
            # Cash might be in different format
            cash = 0
            if isinstance(cash_response, dict):
                cash = cash_response.get('value', cash_response.get('amount', 0))
            
            # Calculate totals from positions
            total_invested = sum(
                float(p.get('netSize', 0)) * float(p.get('averageBuyIn', 0)) 
                for p in positions
            )
            total_value = float(net_value) if net_value else sum(
                float(p.get('netValue', 0)) for p in positions
            )
            
            total_profit = total_value - total_invested
            total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
            
            return {
                "success": True,
                "data": {
                    "totalValue": total_value + cash,
                    "investedAmount": total_invested,
                    "cash": cash,
                    "totalProfit": total_profit,
                    "totalProfitPercent": total_profit_pct,
                    "positions": [
                        {
                            "name": p.get('name', p.get('instrumentId', 'Unknown')),
                            "isin": p.get('instrumentId', ''),
                            "quantity": float(p.get('netSize', 0)),
                            "averageBuyIn": float(p.get('averageBuyIn', 0)),
                            "value": float(p.get('netValue', 0)),
                            "profit": float(p.get('netValue', 0)) - (float(p.get('netSize', 0)) * float(p.get('averageBuyIn', 0))),
                        }
                        for p in positions
                    ]
                }
            }
        except Exception as e:
            log.error(f"Portfolio fetch failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _fetch_all_data(self) -> Dict[str, Any]:
        """Fetch all portfolio data with instrument names. Skip ticker prices (too slow)."""
        try:
            if not self.api or not self.is_connected:
                return {"success": False, "error": "Not connected"}

            log.info("Fetching compact portfolio...")
            
            # Get compact portfolio
            await self.api.compact_portfolio()
            sub_id, sub_params, portfolio_response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            log.info(f"Got portfolio with {len(portfolio_response.get('positions', []))} positions")
            
            # Get cash balance - TR returns an array: [{amount, currencyId}, ...]
            await self.api.cash()
            sub_id, sub_params, cash_response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            log.info(f"Cash response type: {type(cash_response)}, value: {cash_response}")
            
            # Parse portfolio data
            positions = portfolio_response.get('positions', [])
            net_value = float(portfolio_response.get('netValue', 0))
            
            # Cash is an array of {amount, currencyId} - typically EUR as first element
            cash = 0.0
            if isinstance(cash_response, list) and len(cash_response) > 0:
                # First element is usually the main cash balance
                cash = float(cash_response[0].get('amount', 0))
                log.info(f"Parsed cash from array: {cash} {cash_response[0].get('currencyId', 'EUR')}")
            elif isinstance(cash_response, dict):
                # Fallback if response format changes
                cash = float(cash_response.get('amount', cash_response.get('value', 0)))
            
            log.info(f"Portfolio netValue from TR: {net_value}, cash: {cash}")
            
            # Fetch instrument names only (skip ticker - too slow and unreliable)
            instrument_cache = self._load_instrument_cache()
            enriched_positions = []
            
            for i, p in enumerate(positions):
                isin = p.get('instrumentId', '')
                qty = float(p.get('netSize', 0))
                avg_buy = float(p.get('averageBuyIn', 0))
                invested = qty * avg_buy
                # TR provides netValue per position in compact_portfolio
                position_value = float(p.get('netValue', 0))
                
                # Default name is ISIN, check cache first
                cached_info = instrument_cache.get(isin, {})
                if isinstance(cached_info, str):
                    # Old cache format - just name string
                    cached_info = {"name": cached_info}
                
                name = cached_info.get("name") or isin
                instrument_type = cached_info.get("typeId", "")
                image_id = cached_info.get("imageId", "")
                
                # Only hit the instrument endpoint if we don't already have a real name.
                if name == isin:
                    try:
                        await self.api.instrument_details(isin)
                        inst_sub_id, inst_params, inst_response = await self.api.recv()
                        await self.api.unsubscribe(inst_sub_id)
                        name = inst_response.get('shortName', inst_response.get('name', isin))
                        instrument_type = inst_response.get('typeId', inst_response.get('type', ''))
                        image_id = inst_response.get('imageId', '')
                        if name and name != isin:
                            instrument_cache[isin] = {
                                "name": name,
                                "typeId": instrument_type,
                                "imageId": image_id,
                            }
                        log.info(f"[{i+1}/{len(positions)}] {isin}: {name} (type={instrument_type}, img={image_id})")
                    except Exception as e:
                        log.warning(f"[{i+1}/{len(positions)}] Could not get name for {isin}: {e}")
                
                # Use TR's netValue if available, otherwise calculate from invested
                current_value = position_value if position_value > 0 else invested
                current_price = current_value / qty if qty > 0 else avg_buy
                profit = current_value - invested
                
                enriched_positions.append({
                    "name": name,
                    "isin": isin,
                    "quantity": qty,
                    "averageBuyIn": avg_buy,
                    "currentPrice": current_price,
                    "value": current_value,
                    "invested": invested,
                    "profit": profit,
                    "instrumentType": instrument_type,  # e.g., "stock", "fund", "crypto", "bond"
                    "imageId": image_id,  # TR's image identifier
                })
            
            total_invested = sum(p['invested'] for p in enriched_positions)
            total_current_value = sum(p['value'] for p in enriched_positions)
            # Use TR's netValue if we have it, otherwise sum of positions
            total_value = net_value if net_value > 0 else total_current_value
            total_profit = total_value - total_invested
            total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
            
            log.info(f"Portfolio summary: invested={total_invested:.2f}, value={total_value:.2f}, profit={total_profit:.2f} ({total_profit_pct:.2f}%)")
            
            # Fetch timeline transactions (for history reconstruction)
            log.info("Fetching timeline transactions...")
            transactions = await self._fetch_timeline_transactions()
            if transactions:
                self._save_transactions_cache(transactions)
            else:
                # Try to load from cache if fetch failed
                transactions = self._load_transactions_cache()
            
            # Build invested series from transactions (needed for all history methods)
            invested_series = self._build_invested_series_from_transactions(transactions)
            log.info(f"Built invested series with {len(invested_series)} cash flow dates")
            
            # Build per-position price histories using Yahoo Finance FIRST
            # (needed for both TR history merge and fallback calculation)
            log.info("Building per-position price histories from Yahoo Finance...")
            position_histories = self._build_position_histories_from_yahoo(
                transactions, enriched_positions
            )
            log.info(f"Built position histories for {len(position_histories)} instruments")
            
            # Try to fetch real portfolio aggregate history from TR API
            aggregate_history = await self._fetch_portfolio_aggregate_history("max")
            
            if aggregate_history and len(aggregate_history) > 5:
                # Use real TR aggregate history if available
                history = aggregate_history
                log.info(f"Using TR aggregate history with {len(history)} points")
                
                # DEBUG: Check what TR returns for invested values
                sample = history[:3] + history[-3:] if len(history) > 6 else history
                for h in sample:
                    log.info(f"  TR history sample: date={h.get('date')}, value={h.get('value')}, invested={h.get('invested')}")
                
                # TR's aggregate history often has incorrect invested values (0 or same as value)
                # Merge with transaction-derived invested amounts for accurate TWR calculation
                if invested_series:
                    # DEBUG: Show invested series sample
                    sorted_dates = sorted(invested_series.keys())
                    for d in sorted_dates[:3]:
                        log.info(f"  Invested series sample: {d} = {invested_series[d]:,.2f}")
                    
                    history = self._merge_history_with_invested(history, invested_series)
                    log.info(f"Merged history with transaction-derived invested values")
                    
                    # DEBUG: Check merged result
                    sample = history[:3] + history[-3:] if len(history) > 6 else history
                    for h in sample:
                        log.info(f"  Merged history sample: date={h.get('date')}, value={h.get('value')}, invested={h.get('invested')}")
            else:
                # Fallback: Build history with actual market values from position histories
                log.info("TR aggregate history unavailable - calculating market values from position prices...")
                history = self._build_history_with_market_values(
                    transactions, position_histories, invested_series, total_value + cash
                )
            
            result = {
                "success": True,
                "data": {
                    "totalValue": total_value + cash,
                    "investedAmount": total_invested,
                    "cash": cash,
                    "totalProfit": total_profit,
                    "totalProfitPercent": total_profit_pct,
                    "positions": enriched_positions,
                    "transactions": transactions,  # Keep ALL transactions
                    "history": history,
                    "positionHistories": position_histories,  # Per-position price histories
                }
            }

            # Persist instrument name cache for next sync.
            if instrument_cache:
                self._save_instrument_cache(instrument_cache)
            
            # Save to local cache
            self._save_portfolio_cache(result)
            
            return result
            
        except Exception as e:
            log.error(f"Fetch all data failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }
    
    def _calculate_and_cache_twr_series(self, history: List[Dict]) -> Dict[str, List]:
        """Pre-calculate TWR series for caching. This avoids recalculation on every chart render.
        
        Returns dict with:
            - dates: list of date strings (YYYY-MM-DD)
            - values: list of portfolio values
            - invested: list of invested amounts  
            - twr: list of TWR percentages (starting at 0%)
            - drawdown: list of drawdown percentages
        """
        if not history or len(history) < 2:
            return {}
        
        import pandas as pd
        
        # Sort and build dataframe
        sorted_history = sorted(history, key=lambda x: x.get('date', ''))
        df = pd.DataFrame(sorted_history)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        # Fill gaps with daily frequency
        df = df.set_index('date')
        full_date_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')
        df = df.reindex(full_date_range).ffill().reset_index().rename(columns={'index': 'date'})
        
        # Calculate TWR series (Time-Weighted Return)
        values = df['value'].values
        invested = df['invested'].values if 'invested' in df.columns else values
        
        twr_cumulative = [0.0]  # Start at 0%
        cumulative_factor = 1.0
        
        for i in range(1, len(df)):
            prev_value = values[i-1]
            curr_value = values[i]
            cash_flow = invested[i] - invested[i-1]  # Change in invested = cash flow
            
            if prev_value > 0:
                adjusted_end = curr_value - cash_flow
                period_return = (adjusted_end / prev_value) - 1
                period_return = max(-0.99, min(period_return, 10.0))  # Clamp
                cumulative_factor *= (1 + period_return)
            
            twr_cumulative.append((cumulative_factor - 1) * 100)
        
        # Calculate drawdown series
        rolling_max = df['value'].expanding().max().replace(0, pd.NA)
        drawdown = ((df['value'] - rolling_max) / rolling_max * 100).fillna(0).tolist()
        
        return {
            'dates': df['date'].dt.strftime('%Y-%m-%d').tolist(),
            'values': [float(v) if pd.notna(v) else None for v in df['value'].tolist()],
            'invested': [float(v) if pd.notna(v) else None for v in invested.tolist()],
            'twr': [float(v) if v is not None else 0.0 for v in twr_cumulative],
            'drawdown': [float(v) if pd.notna(v) else 0.0 for v in drawdown],
        }
    
    def _save_portfolio_cache(self, data: Dict[str, Any]):
        """Save portfolio data to local cache with pre-calculated series."""
        cache_file = TR_CREDENTIALS_DIR / "portfolio_cache.json"
        try:
            import datetime
            data['cached_at'] = datetime.datetime.now().isoformat()
            
            # Pre-calculate TWR and drawdown series for faster chart rendering
            history = data.get('data', {}).get('history', [])
            if history:
                cached_series = self._calculate_and_cache_twr_series(history)
                data['data']['cachedSeries'] = cached_series
                log.info(f"Pre-calculated chart series with {len(cached_series.get('dates', []))} data points")
            
            with open(cache_file, 'w') as f:
                json.dump(data, f)
            log.info("Portfolio data cached")
        except Exception as e:
            log.error(f"Failed to cache portfolio: {e}")
    
    def _load_portfolio_cache(self) -> Optional[Dict[str, Any]]:
        """Load portfolio data from local cache."""
        cache_file = TR_CREDENTIALS_DIR / "portfolio_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log.error(f"Failed to load cache: {e}")
        return None
    
    async def _reconnect(self, encrypted_credentials: str = None) -> Dict[str, Any]:
        """Reconnect using encrypted credentials from browser."""
        try:
            # Decrypt credentials from browser storage
            if encrypted_credentials:
                if not self.set_credentials_from_encrypted(encrypted_credentials):
                    return {"success": False, "error": "Invalid stored credentials"}
            
            if not self.phone_no or not self.pin:
                return {"success": False, "error": "No credentials available", "needs_reauth": True}
            
            if not TR_KEYFILE.exists():
                return {"success": False, "error": "Session expired - please log in again", "needs_reauth": True}
            
            TR_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            
            self.api = TradeRepublicApi(
                phone_no=self.phone_no,
                pin=self.pin,
                keyfile=str(TR_KEYFILE)
            )
            
            # Try to login with existing keyfile - THIS IS SYNC, not async!
            self.api.login()
            self.is_connected = True
            
            return {
                "success": True,
                "message": "Reconnected successfully"
            }
        except Exception as e:
            log.error(f"Reconnect failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "needs_reauth": True
            }


# Global connection instance
_connection: Optional[TRConnection] = None


def get_connection() -> TRConnection:
    """Get or create the TR connection instance."""
    global _connection
    if _connection is None:
        _connection = TRConnection()
    return _connection


# Public API functions (sync wrappers)

def has_saved_credentials() -> bool:
    """Check if TR credentials are saved."""
    return get_connection().has_credentials()


def initiate_login(phone_no: str, pin: str) -> Dict[str, Any]:
    """Start the login process - sends verification code to TR app."""
    conn = get_connection()
    return conn.run(conn._initiate_web_login(phone_no, pin))


def complete_login(code: str) -> Dict[str, Any]:
    """Complete login with the 4-digit verification code."""
    conn = get_connection()
    return conn.run(conn._complete_web_login(code))


def fetch_portfolio() -> Dict[str, Any]:
    """Fetch current portfolio data."""
    conn = get_connection()
    return conn.run_serialized(conn._fetch_portfolio())


def fetch_all_data() -> Dict[str, Any]:
    """Fetch all portfolio data including history.
    
    This ALWAYS fetches fresh data from TR when called.
    The cache is only used for page loads (via get_cached_portfolio).
    """
    conn = get_connection()
    return conn.run_serialized(conn._fetch_all_data())


def get_cached_portfolio() -> Optional[Dict[str, Any]]:
    """Get cached portfolio data without connecting."""
    conn = get_connection()
    return conn._load_portfolio_cache()


def get_cached_transactions() -> List[Dict]:
    """Get cached transactions without connecting."""
    conn = get_connection()
    return conn._load_transactions_cache()


def reconnect(encrypted_credentials: str = None) -> Dict[str, Any]:
    """Try to reconnect using encrypted credentials from browser."""
    conn = get_connection()
    return conn.run_serialized(conn._reconnect(encrypted_credentials))


def disconnect():
    """Disconnect and clear credentials."""
    conn = get_connection()
    conn.clear_credentials()


def has_keyfile() -> bool:
    """Check if keyfile exists for reconnect."""
    return get_connection().has_keyfile()


def is_connected() -> bool:
    """Check if currently connected."""
    return get_connection().is_connected
