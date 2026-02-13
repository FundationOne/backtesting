"""
GoCardless Bank Account Data API (formerly Nordigen)
PSD2 Open Banking integration for transaction sync.

Free tier: up to 50 connections, 90-day transaction history.
Sign up at https://bankaccountdata.gocardless.com/
"""

import os
import json
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import requests

# ── Config ──────────────────────────────────────────────────────────────
GC_BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"

# Credentials from environment or set in Settings
GC_SECRET_ID = os.environ.get("GOCARDLESS_SECRET_ID", "")
GC_SECRET_KEY = os.environ.get("GOCARDLESS_SECRET_KEY", "")

# Redirect URL after bank authentication (update when deploying)
GC_REDIRECT_URL = os.environ.get("GOCARDLESS_REDIRECT_URL", "http://localhost:8888/banksync")

# Local cache directory
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "bank_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Token cache
_token_cache: Dict[str, Any] = {"access": None, "expires_at": 0}

# ── Helpers ─────────────────────────────────────────────────────────────

def _user_cache_dir(user_id: str) -> Path:
    """Per-user cache directory based on hashed user_id."""
    hashed = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    d = _CACHE_DIR / hashed
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_json(path: Path, data: Any):
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


# ── Authentication ──────────────────────────────────────────────────────

def get_credentials() -> Tuple[str, str]:
    """Return (secret_id, secret_key) from env or stored config."""
    sid = GC_SECRET_ID
    skey = GC_SECRET_KEY
    # Also check a local config file
    cfg_path = _CACHE_DIR / "gc_credentials.json"
    if (not sid or not skey) and cfg_path.exists():
        cfg = _load_json(cfg_path)
        if cfg:
            sid = cfg.get("secret_id", sid)
            skey = cfg.get("secret_key", skey)
    return sid, skey


def save_credentials(secret_id: str, secret_key: str):
    """Persist GoCardless credentials locally."""
    cfg_path = _CACHE_DIR / "gc_credentials.json"
    _save_json(cfg_path, {"secret_id": secret_id, "secret_key": secret_key})


def has_credentials() -> bool:
    sid, skey = get_credentials()
    return bool(sid and skey)


def _get_access_token() -> Optional[str]:
    """Obtain or reuse a valid access token."""
    now = time.time()
    if _token_cache["access"] and _token_cache["expires_at"] > now + 30:
        return _token_cache["access"]

    sid, skey = get_credentials()
    if not sid or not skey:
        return None

    try:
        resp = requests.post(
            f"{GC_BASE_URL}/token/new/",
            json={"secret_id": sid, "secret_key": skey},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _token_cache["access"] = data["access"]
        _token_cache["expires_at"] = now + data.get("access_expires", 86400)
        return data["access"]
    except Exception as e:
        print(f"[GoCardless] Token error: {e}")
        return None


def _headers() -> Dict[str, str]:
    token = _get_access_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── Institutions (banks) ───────────────────────────────────────────────

def list_institutions(country: str = "DE") -> List[Dict]:
    """List available banks for a country. Cached for 24h."""
    cache_path = _CACHE_DIR / f"institutions_{country.lower()}.json"
    cached = _load_json(cache_path)
    if cached and cached.get("_ts", 0) > time.time() - 86400:
        return cached.get("data", [])

    h = _headers()
    if not h:
        return []

    try:
        resp = requests.get(
            f"{GC_BASE_URL}/institutions/?country={country}",
            headers=h,
            timeout=15,
        )
        resp.raise_for_status()
        institutions = resp.json()
        _save_json(cache_path, {"_ts": time.time(), "data": institutions})
        return institutions
    except Exception as e:
        print(f"[GoCardless] Institutions error: {e}")
        return []


# ── Requisitions (bank connections) ────────────────────────────────────

def create_requisition(
    institution_id: str,
    redirect_url: str = "",
    reference: str = "",
    user_id: str = "_default",
) -> Optional[Dict]:
    """Create a new bank connection requisition. Returns the requisition data
    including the authentication link the user must visit."""
    h = _headers()
    if not h:
        return None

    if not reference:
        reference = f"apex_{user_id}_{int(time.time())}"

    if not redirect_url:
        redirect_url = GC_REDIRECT_URL

    payload = {
        "redirect": redirect_url,
        "institution_id": institution_id,
        "reference": reference,
        "user_language": "DE",
    }

    try:
        resp = requests.post(
            f"{GC_BASE_URL}/requisitions/",
            headers=h,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # Cache the requisition info
        udir = _user_cache_dir(user_id)
        reqs = _load_json(udir / "requisitions.json") or []
        reqs.append({
            "id": data["id"],
            "institution_id": institution_id,
            "status": data.get("status", "CR"),
            "link": data.get("link", ""),
            "created": datetime.utcnow().isoformat(),
            "accounts": data.get("accounts", []),
        })
        _save_json(udir / "requisitions.json", reqs)
        return data
    except Exception as e:
        print(f"[GoCardless] Requisition error: {e}")
        return None


def get_requisition(requisition_id: str) -> Optional[Dict]:
    """Get status of a requisition."""
    h = _headers()
    if not h:
        return None
    try:
        resp = requests.get(
            f"{GC_BASE_URL}/requisitions/{requisition_id}/",
            headers=h,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[GoCardless] Get requisition error: {e}")
        return None


def get_user_requisitions(user_id: str) -> List[Dict]:
    """Get all cached requisitions for a user."""
    udir = _user_cache_dir(user_id)
    return _load_json(udir / "requisitions.json") or []


def refresh_requisition_status(requisition_id: str, user_id: str) -> Optional[str]:
    """Refresh a requisition's status from the API and update cache.
    Returns the new status or None on error."""
    data = get_requisition(requisition_id)
    if not data:
        return None

    udir = _user_cache_dir(user_id)
    reqs = _load_json(udir / "requisitions.json") or []
    for r in reqs:
        if r["id"] == requisition_id:
            r["status"] = data.get("status", r.get("status"))
            r["accounts"] = data.get("accounts", r.get("accounts", []))
            break
    _save_json(udir / "requisitions.json", reqs)
    return data.get("status")


# ── Accounts ───────────────────────────────────────────────────────────

def get_account_details(account_id: str) -> Optional[Dict]:
    """Fetch account metadata (IBAN, owner name, etc.)."""
    h = _headers()
    if not h:
        return None
    try:
        resp = requests.get(
            f"{GC_BASE_URL}/accounts/{account_id}/details/",
            headers=h,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("account", resp.json())
    except Exception as e:
        print(f"[GoCardless] Account details error: {e}")
        return None


def get_account_balances(account_id: str) -> Optional[List[Dict]]:
    """Fetch account balances."""
    h = _headers()
    if not h:
        return None
    try:
        resp = requests.get(
            f"{GC_BASE_URL}/accounts/{account_id}/balances/",
            headers=h,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("balances", [])
    except Exception as e:
        print(f"[GoCardless] Balances error: {e}")
        return None


def get_account_transactions(
    account_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Optional[Dict]:
    """Fetch transactions for an account.
    Returns {"booked": [...], "pending": [...]}."""
    h = _headers()
    if not h:
        return None

    params: Dict[str, str] = {}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to

    try:
        resp = requests.get(
            f"{GC_BASE_URL}/accounts/{account_id}/transactions/",
            headers=h,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("transactions", data)
    except Exception as e:
        print(f"[GoCardless] Transactions error: {e}")
        return None


# ── Transaction caching + delta sync ──────────────────────────────────

def sync_transactions(
    account_id: str,
    user_id: str = "_default",
    force_full: bool = False,
) -> List[Dict]:
    """Sync transactions for an account with delta support.
    Returns all booked transactions (merged old + new)."""
    udir = _user_cache_dir(user_id)
    cache_file = udir / f"transactions_{account_id}.json"
    cached = _load_json(cache_file)

    existing_txs: List[Dict] = []
    last_date: Optional[str] = None

    if cached and not force_full:
        existing_txs = cached.get("transactions", [])
        last_date = cached.get("last_sync_date")

    # Determine date range for delta
    date_from = None
    if last_date and not force_full:
        # Overlap by 3 days to catch any late-arriving transactions
        dt = datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=3)
        date_from = dt.strftime("%Y-%m-%d")

    raw = get_account_transactions(account_id, date_from=date_from)
    if raw is None:
        return existing_txs  # Return cached on error

    new_booked = raw.get("booked", [])

    # Merge: deduplicate by transactionId or internalTransactionId
    seen_ids = set()
    merged = []

    for tx in existing_txs + new_booked:
        tx_id = tx.get("transactionId") or tx.get("internalTransactionId") or ""
        if not tx_id:
            # Generate a pseudo-ID from amount + date + info
            tx_id = hashlib.md5(
                json.dumps(tx, sort_keys=True, default=str).encode()
            ).hexdigest()
            tx["_generated_id"] = tx_id
        if tx_id not in seen_ids:
            seen_ids.add(tx_id)
            merged.append(tx)

    # Sort by booking date descending
    merged.sort(
        key=lambda t: t.get("bookingDate", t.get("valueDate", "1970-01-01")),
        reverse=True,
    )

    # Save
    today = datetime.utcnow().strftime("%Y-%m-%d")
    _save_json(cache_file, {
        "account_id": account_id,
        "last_sync_date": today,
        "last_sync_ts": time.time(),
        "transaction_count": len(merged),
        "transactions": merged,
    })

    return merged


def get_cached_transactions(account_id: str, user_id: str = "_default") -> List[Dict]:
    """Return locally cached transactions without hitting the API."""
    udir = _user_cache_dir(user_id)
    cache_file = udir / f"transactions_{account_id}.json"
    cached = _load_json(cache_file)
    if cached:
        return cached.get("transactions", [])
    return []


# ── Transaction normalisation ─────────────────────────────────────────

def normalize_transaction(tx: Dict) -> Dict:
    """Normalise a GoCardless transaction into a flat dict for display."""
    amount_raw = tx.get("transactionAmount", {})
    amount = float(amount_raw.get("amount", 0))
    currency = amount_raw.get("currency", "EUR")

    # Build a clean recipient / remitter name
    creditor = tx.get("creditorName", "")
    debtor = tx.get("debtorName", "")
    counterparty = creditor or debtor or ""

    # Build description from multiple possible fields
    info_parts = []
    for key in ("remittanceInformationUnstructured",
                "remittanceInformationUnstructuredArray",
                "remittanceInformationStructured",
                "additionalInformation"):
        val = tx.get(key)
        if val:
            if isinstance(val, list):
                info_parts.extend(val)
            else:
                info_parts.append(str(val))
    description = " | ".join(info_parts) if info_parts else ""

    return {
        "id": tx.get("transactionId") or tx.get("internalTransactionId")
              or tx.get("_generated_id", ""),
        "date": tx.get("bookingDate", tx.get("valueDate", "")),
        "amount": amount,
        "currency": currency,
        "counterparty": counterparty,
        "description": description,
        "category": tx.get("_category", ""),
        "rule_id": tx.get("_rule_id", ""),
        "raw": tx,
    }


# ── Transaction categorisation (OpenAI) ───────────────────────────────

_DEFAULT_CATEGORIES_PATH = Path(__file__).resolve().parent.parent / "data" / "default_categories.json"


def load_default_categories() -> List[str]:
    """Load the default category list."""
    if _DEFAULT_CATEGORIES_PATH.exists():
        return json.loads(_DEFAULT_CATEGORIES_PATH.read_text(encoding="utf-8"))
    return [
        "Groceries", "Rent", "Utilities", "Insurance", "Salary",
        "Dining Out", "Transport", "Entertainment", "Subscriptions",
        "Healthcare", "Shopping", "Transfer", "Cash Withdrawal",
        "Savings", "Investment", "Other",
    ]


def categorise_transactions_batch(
    transactions: List[Dict],
    api_key: str,
    categories: Optional[List[str]] = None,
    batch_size: int = 30,
) -> List[Dict]:
    """Use OpenAI to categorise a batch of transactions.
    Updates each tx dict with a '_category' field."""
    if not api_key:
        return transactions

    if categories is None:
        categories = load_default_categories()

    cat_list = ", ".join(categories)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except Exception as e:
        print(f"[Categorise] OpenAI init error: {e}")
        return transactions

    # Process in batches
    uncategorised = [t for t in transactions if not t.get("_category")]
    for i in range(0, len(uncategorised), batch_size):
        batch = uncategorised[i:i + batch_size]
        descriptions = []
        for idx, tx in enumerate(batch):
            norm = normalize_transaction(tx)
            line = (
                f"{idx}|{norm['date']}|{norm['amount']:.2f} {norm['currency']}"
                f"|{norm['counterparty']}|{norm['description'][:120]}"
            )
            descriptions.append(line)

        prompt = (
            f"Categorise each bank transaction into exactly one of these categories:\n"
            f"{cat_list}\n\n"
            f"Transactions (index|date|amount|counterparty|description):\n"
            + "\n".join(descriptions) +
            "\n\nReturn ONLY a JSON array of objects with keys 'index' (int) and 'category' (string). "
            "No commentary."
        )

        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You categorise bank transactions. Be concise."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2000,
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
            results = json.loads(raw)
            for item in results:
                idx = int(item["index"])
                if 0 <= idx < len(batch):
                    batch[idx]["_category"] = item["category"]
        except Exception as e:
            print(f"[Categorise] Batch error: {e}")

    return transactions


# ── Rules engine ──────────────────────────────────────────────────────

def load_rules(user_id: str) -> List[Dict]:
    """Load user's recurring-transaction rules."""
    udir = _user_cache_dir(user_id)
    return _load_json(udir / "rules.json") or []


def save_rules(user_id: str, rules: List[Dict]):
    """Persist user's rules."""
    udir = _user_cache_dir(user_id)
    _save_json(udir / "rules.json", rules)


def add_rule(
    user_id: str,
    name: str,
    counterparty_pattern: str,
    category: str,
    expected_amount: Optional[float] = None,
    amount_tolerance: float = 0.1,  # ±10% by default
    frequency_days: int = 30,
    rule_type: str = "recurring",  # recurring | one-time
) -> Dict:
    """Create a new rule and persist it."""
    rules = load_rules(user_id)
    rule = {
        "id": hashlib.md5(f"{name}_{counterparty_pattern}_{time.time()}".encode()).hexdigest()[:12],
        "name": name,
        "counterparty_pattern": counterparty_pattern.lower(),
        "category": category,
        "expected_amount": expected_amount,
        "amount_tolerance": amount_tolerance,
        "frequency_days": frequency_days,
        "rule_type": rule_type,
        "created": datetime.utcnow().isoformat(),
        "active": True,
    }
    rules.append(rule)
    save_rules(user_id, rules)
    return rule


def delete_rule(user_id: str, rule_id: str):
    """Delete a rule by ID."""
    rules = load_rules(user_id)
    rules = [r for r in rules if r["id"] != rule_id]
    save_rules(user_id, rules)


def apply_rules(transactions: List[Dict], rules: List[Dict]) -> List[Dict]:
    """Apply rules to transactions. Sets _category and _rule_id on matches."""
    active_rules = [r for r in rules if r.get("active", True)]
    for tx in transactions:
        if tx.get("_rule_id"):
            continue  # Already matched
        norm = normalize_transaction(tx)
        cp = norm["counterparty"].lower()
        desc = norm["description"].lower()
        for rule in active_rules:
            pattern = rule["counterparty_pattern"]
            if pattern and (pattern in cp or pattern in desc):
                # Check amount tolerance if specified
                if rule.get("expected_amount") is not None:
                    expected = abs(rule["expected_amount"])
                    actual = abs(norm["amount"])
                    tol = rule.get("amount_tolerance", 0.1)
                    if actual < expected * (1 - tol) or actual > expected * (1 + tol):
                        continue
                tx["_category"] = rule["category"]
                tx["_rule_id"] = rule["id"]
                break
    return transactions


# ── Monitoring helpers ────────────────────────────────────────────────

def get_rule_matches(
    transactions: List[Dict],
    rule: Dict,
    months_back: int = 6,
) -> List[Dict]:
    """Find all transactions matching a specific rule within a time window."""
    cutoff = (datetime.utcnow() - timedelta(days=months_back * 30)).strftime("%Y-%m-%d")
    matches = []
    pattern = rule["counterparty_pattern"]
    for tx in transactions:
        norm = normalize_transaction(tx)
        if norm["date"] < cutoff:
            continue
        cp = norm["counterparty"].lower()
        desc = norm["description"].lower()
        if pattern and (pattern in cp or pattern in desc):
            if rule.get("expected_amount") is not None:
                expected = abs(rule["expected_amount"])
                actual = abs(norm["amount"])
                tol = rule.get("amount_tolerance", 0.1)
                if actual < expected * (1 - tol) or actual > expected * (1 + tol):
                    continue
            matches.append(norm)
    matches.sort(key=lambda m: m["date"])
    return matches


def compute_monitoring_summary(
    transactions: List[Dict],
    rules: List[Dict],
    months_back: int = 6,
) -> List[Dict]:
    """Compute a monitoring summary for each rule: expected vs actual occurrences,
    cumulative amounts, last seen date, status (OK / OVERDUE / MISSING)."""
    summaries = []
    now = datetime.utcnow()

    for rule in rules:
        if not rule.get("active", True):
            continue
        if rule.get("rule_type") == "one-time":
            continue

        matches = get_rule_matches(transactions, rule, months_back)
        freq = rule.get("frequency_days", 30)
        expected_amount = rule.get("expected_amount")

        # Determine last occurrence
        last_date = None
        if matches:
            last_date = matches[-1]["date"]

        # How many expected in the window?
        window_days = months_back * 30
        expected_count = max(1, window_days // freq)
        actual_count = len(matches)

        # Cumulative amount
        cumulative = sum(m["amount"] for m in matches)

        # Status
        status = "OK"
        if last_date:
            days_since = (now - datetime.strptime(last_date, "%Y-%m-%d")).days
            if days_since > freq * 1.5:
                status = "OVERDUE"
        else:
            status = "MISSING"

        summaries.append({
            "rule_id": rule["id"],
            "name": rule["name"],
            "category": rule["category"],
            "frequency_days": freq,
            "expected_amount": expected_amount,
            "expected_count": expected_count,
            "actual_count": actual_count,
            "cumulative": round(cumulative, 2),
            "last_date": last_date,
            "status": status,
            "matches": matches,
        })

    return summaries


# ── Delete requisition / disconnect ───────────────────────────────────

def delete_requisition(requisition_id: str, user_id: str):
    """Delete a requisition from the API and local cache."""
    h = _headers()
    if h:
        try:
            requests.delete(
                f"{GC_BASE_URL}/requisitions/{requisition_id}/",
                headers=h,
                timeout=15,
            )
        except Exception:
            pass

    udir = _user_cache_dir(user_id)
    reqs = _load_json(udir / "requisitions.json") or []
    reqs = [r for r in reqs if r["id"] != requisition_id]
    _save_json(udir / "requisitions.json", reqs)
