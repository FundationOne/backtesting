"""
Bank Account Data API — GoCardless (formerly Nordigen) integration.
PSD2 Open Banking for transaction sync.

Sign up at https://bankaccountdata.gocardless.com
You need a secret_id and secret_key.

Flow:
1. App authenticates via JWT token (POST /token/new/)
2. App lists available banks (GET /institutions/?country=XX)
3. App creates an end-user agreement + requisition (link URL)
4. User authenticates with their bank in GoCardless hosted UI
5. User is redirected back; app polls requisition for status=LN
6. App fetches accounts + transactions using account UUIDs
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
GC_BASE = "https://bankaccountdata.gocardless.com/api/v2"

# Credentials from environment or stored config
GC_SECRET_ID = os.environ.get("GC_SECRET_ID", "")
GC_SECRET_KEY = os.environ.get("GC_SECRET_KEY", "")

# Redirect URL after bank authentication (set via env in production)
BANK_REDIRECT_URL = os.environ.get(
    "BANK_REDIRECT_URL", "http://localhost:8888/banksync"
)

# Local cache directory
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "bank_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Token cache  (access valid 24h, refresh valid 30d)
_token_cache: Dict[str, Any] = {
    "access": None,
    "refresh": None,
    "access_exp": 0,
    "refresh_exp": 0,
}


# ── Helpers ─────────────────────────────────────────────────────────────

def _user_cache_dir(user_id: str) -> Path:
    """Per-user cache directory."""
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


# ── Credential management ──────────────────────────────────────────────

def get_credentials() -> Tuple[str, str]:
    """Return (secret_id, secret_key) from environment variables."""
    return GC_SECRET_ID, GC_SECRET_KEY


def has_credentials() -> bool:
    sid, skey = get_credentials()
    return bool(sid and skey)


# ── Authentication ──────────────────────────────────────────────────────

def _get_access_token() -> Optional[str]:
    """Obtain or reuse a valid JWT access token.

    GoCardless BAD auth:
      POST /token/new/    → {access, access_expires (86400), refresh, refresh_expires (2592000)}
      POST /token/refresh/ → {access, access_expires}
    """
    now = time.time()

    # 1) Cached access token still valid (with 60s margin)
    if _token_cache["access"] and _token_cache["access_exp"] > now + 60:
        return _token_cache["access"]

    # 2) Refresh token still valid → refresh
    if _token_cache["refresh"] and _token_cache["refresh_exp"] > now + 60:
        try:
            resp = requests.post(
                f"{GC_BASE}/token/refresh/",
                json={"refresh": _token_cache["refresh"]},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            _token_cache["access"] = data["access"]
            _token_cache["access_exp"] = now + data.get("access_expires", 86400)
            return _token_cache["access"]
        except Exception as e:
            print(f"[GoCardless] Token refresh failed: {e}")
            # Fall through to full auth

    # 3) Full authentication with secret_id / secret_key
    sid, skey = get_credentials()
    if not sid or not skey:
        return None

    try:
        resp = requests.post(
            f"{GC_BASE}/token/new/",
            json={"secret_id": sid, "secret_key": skey},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _token_cache["access"] = data["access"]
        _token_cache["refresh"] = data["refresh"]
        _token_cache["access_exp"] = now + data.get("access_expires", 86400)
        _token_cache["refresh_exp"] = now + data.get("refresh_expires", 2592000)
        return _token_cache["access"]
    except Exception as e:
        print(f"[GoCardless] Token error: {e}")
        return None


def _auth_headers() -> Dict[str, str]:
    """Return Authorization + Content-Type headers, or empty dict on failure."""
    token = _get_access_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── Institutions (banks) ──────────────────────────────────────────────

def list_institutions(country: str = "DE") -> List[Dict]:
    """List available banks for a country. Cached for 24 h.

    GET /institutions/?country=XX
    Returns [{id, name, bic, transaction_total_days, logo, countries, ...}]
    """
    cache_path = _CACHE_DIR / f"institutions_{country.lower()}.json"
    cached = _load_json(cache_path)
    if cached and cached.get("_ts", 0) > time.time() - 86400:
        return cached.get("data", [])

    h = _auth_headers()
    if not h:
        return cached.get("data", []) if cached else []

    try:
        resp = requests.get(
            f"{GC_BASE}/institutions/",
            headers=h,
            params={"country": country},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
        institutions = raw if isinstance(raw, list) else raw.get("results", raw.get("data", []))

        normalised: List[Dict] = []
        for inst in institutions:
            normalised.append({
                "id": inst.get("id", ""),
                "name": inst.get("name", ""),
                "logo": inst.get("logo", ""),
                "countries": inst.get("countries", [country]),
                "transaction_total_days": inst.get("transaction_total_days", "90"),
                "bic": inst.get("bic", ""),
            })
        _save_json(cache_path, {"_ts": time.time(), "data": normalised})
        return normalised
    except Exception as e:
        print(f"[GoCardless] Institutions error: {e}")
        return cached.get("data", []) if cached else []


# ── list_providers alias (backward-compat) ────────────────────────────

def list_providers(market: str = "DE") -> List[Dict]:
    """Alias for list_institutions() — kept for interface compatibility."""
    return list_institutions(market)


# ── End-User Agreement + Requisition (bank connection) ────────────────

def create_agreement(
    institution_id: str,
    max_historical_days: int = 730,
    access_valid_for_days: int = 180,
) -> Optional[Dict]:
    """Create an end-user agreement (EUA) for an institution.

    POST /agreements/enduser/
    Returns {id, created, institution_id, max_historical_days, access_valid_for_days, access_scope, accepted, ...}
    """
    h = _auth_headers()
    if not h:
        return None

    # Clamp max_historical_days to what the institution supports
    institutions = list_institutions()
    inst_info = next((i for i in institutions if i["id"] == institution_id), None)
    if inst_info:
        inst_max = int(inst_info.get("transaction_total_days", "90") or "90")
        max_historical_days = min(max_historical_days, inst_max)

    try:
        resp = requests.post(
            f"{GC_BASE}/agreements/enduser/",
            headers=h,
            json={
                "institution_id": institution_id,
                "max_historical_days": max_historical_days,
                "access_valid_for_days": access_valid_for_days,
                "access_scope": ["balances", "details", "transactions"],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[GoCardless] Agreement error: {e}")
        return None


def create_requisition(
    institution_id: str,
    redirect_url: Optional[str] = None,
    agreement_id: Optional[str] = None,
    reference: Optional[str] = None,
    user_language: str = "EN",
) -> Optional[Dict]:
    """Create a requisition (bank-connection link) for the user.

    POST /requisitions/
    Returns {id, created, redirect, status, institution_id, agreement, link, ...}
    """
    h = _auth_headers()
    if not h:
        return None

    body: Dict[str, Any] = {
        "redirect": redirect_url or BANK_REDIRECT_URL,
        "institution_id": institution_id,
        "user_language": user_language,
    }
    if agreement_id:
        body["agreement"] = agreement_id
    if reference:
        body["reference"] = reference

    try:
        resp = requests.post(
            f"{GC_BASE}/requisitions/",
            headers=h,
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[GoCardless] Requisition error: {e}")
        return None


def create_connection(
    user_id: str = "_default",
    market: str = "DE",
    institution_id: Optional[str] = None,
) -> Optional[Dict]:
    """High-level: create agreement + requisition and save locally.

    If institution_id is omitted, returns None (user must pick a bank).
    Returns {id, link, requisition_id} or None on failure.
    """
    if not institution_id:
        return None

    # 1) Create end-user agreement
    agreement = create_agreement(institution_id)
    agreement_id = agreement["id"] if agreement else None

    # 2) Create requisition
    reference = f"apex_{user_id}_{int(time.time())}"
    requisition = create_requisition(
        institution_id=institution_id,
        agreement_id=agreement_id,
        reference=reference,
    )
    if not requisition:
        return None

    req_id = requisition.get("id", "")
    link = requisition.get("link", "")

    # 3) Persist connection reference locally
    udir = _user_cache_dir(user_id)
    connections = _load_json(udir / "connections.json") or []
    connections.append({
        "id": reference,
        "requisition_id": req_id,
        "agreement_id": agreement_id,
        "institution_id": institution_id,
        "status": "CR",
        "link": link,
        "created": datetime.utcnow().isoformat(),
        "market": market,
        "accounts": [],
    })
    _save_json(udir / "connections.json", connections)

    return {"id": reference, "link": link, "requisition_id": req_id}


def get_requisition_status(requisition_id: str) -> Optional[Dict]:
    """Poll a requisition's status.

    GET /requisitions/{id}/
    Returns {id, status, accounts, institution_id, ...}

    Status codes: CR=Created, GC=GivingConsent, UA=Undergoing Authentication,
                  RJ=Rejected, SA=SelectingAccounts, GA=GrantingAccess,
                  LN=Linked, SU=Suspended, EX=Expired
    """
    h = _auth_headers()
    if not h:
        return None

    try:
        resp = requests.get(
            f"{GC_BASE}/requisitions/{requisition_id}/",
            headers=h,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[GoCardless] Requisition status error: {e}")
        return None


def complete_connection(
    requisition_id: str,
    user_id: str = "_default",
) -> bool:
    """Check requisition status.  If LN (Linked), save the account UUIDs.

    Returns True if the connection is now linked with accounts.
    """
    data = get_requisition_status(requisition_id)
    if not data:
        return False

    status = data.get("status", "")
    accounts = data.get("accounts", [])

    udir = _user_cache_dir(user_id)
    connections = _load_json(udir / "connections.json") or []

    for conn in connections:
        if conn.get("requisition_id") == requisition_id:
            conn["status"] = status
            if accounts:
                conn["accounts"] = accounts
            break

    _save_json(udir / "connections.json", connections)
    return status == "LN" and bool(accounts)


# ── Connections ──────────────────────────────────────────────────────

def get_user_connections(user_id: str) -> List[Dict]:
    """Get all cached connections for a user."""
    udir = _user_cache_dir(user_id)
    return _load_json(udir / "connections.json") or []


# ── Accounts ─────────────────────────────────────────────────────────

def _fetch_account_metadata(account_id: str, h: Dict[str, str]) -> Dict:
    """GET /accounts/{id}/  → {id, created, iban, institution_id, status, ...}"""
    try:
        resp = requests.get(f"{GC_BASE}/accounts/{account_id}/", headers=h, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[GoCardless] Account meta error ({account_id}): {e}")
        return {}


def _fetch_account_details(account_id: str, h: Dict[str, str]) -> Dict:
    """GET /accounts/{id}/details/  → {account: {iban, currency, ownerName, name, ...}}"""
    try:
        resp = requests.get(f"{GC_BASE}/accounts/{account_id}/details/", headers=h, timeout=15)
        resp.raise_for_status()
        return resp.json().get("account", {})
    except Exception as e:
        print(f"[GoCardless] Account details error ({account_id}): {e}")
        return {}


def _fetch_account_balances(account_id: str, h: Dict[str, str]) -> List[Dict]:
    """GET /accounts/{id}/balances/  → {balances: [{balanceAmount: {amount, currency}, ...}]}"""
    try:
        resp = requests.get(f"{GC_BASE}/accounts/{account_id}/balances/", headers=h, timeout=15)
        resp.raise_for_status()
        return resp.json().get("balances", [])
    except Exception as e:
        print(f"[GoCardless] Account balances error ({account_id}): {e}")
        return []


def fetch_accounts(user_id: str = "_default") -> List[Dict]:
    """Fetch all accounts from all linked connections.

    For each account UUID in each connection, calls:
      /accounts/{id}/           → metadata (status, institution)
      /accounts/{id}/details/   → iban, currency, ownerName
      /accounts/{id}/balances/  → balance amounts
    Returns normalised list of account dicts.
    """
    h = _auth_headers()
    if not h:
        udir = _user_cache_dir(user_id)
        cached = _load_json(udir / "accounts.json")
        return cached or []

    # Gather all account UUIDs from linked connections
    connections = get_user_connections(user_id)
    account_ids: List[str] = []
    for conn in connections:
        if conn.get("status") == "LN":
            account_ids.extend(conn.get("accounts", []))

    if not account_ids:
        return []

    normalised: List[Dict] = []
    for aid in account_ids:
        meta = _fetch_account_metadata(aid, h)
        details = _fetch_account_details(aid, h)
        balances_raw = _fetch_account_balances(aid, h)

        # Best balance: prefer closingBooked or interimAvailable
        balance = None
        currency = details.get("currency", "EUR")
        for bal in balances_raw:
            bal_type = bal.get("balanceType", "")
            amt = bal.get("balanceAmount", {})
            if bal_type in ("closingBooked", "interimAvailable", "expected"):
                balance = float(amt.get("amount", 0))
                currency = amt.get("currency", currency)
                break
        if balance is None and balances_raw:
            amt = balances_raw[0].get("balanceAmount", {})
            balance = float(amt.get("amount", 0))
            currency = amt.get("currency", currency)

        iban = details.get("iban", meta.get("iban", ""))
        owner = details.get("ownerName", "")
        name = details.get("name", "") or owner or iban or aid

        normalised.append({
            "account_id": aid,
            "iban": iban,
            "name": name,
            "balance": balance,
            "currency": currency,
            "type": details.get("cashAccountType", ""),
            "status": meta.get("status", "READY"),
            "institution_id": meta.get("institution_id", ""),
        })

    # Cache
    udir = _user_cache_dir(user_id)
    _save_json(udir / "accounts.json", normalised)
    return normalised


def get_account_balances(account_id: str) -> Optional[List[Dict]]:
    """Fetch balances for a specific account."""
    h = _auth_headers()
    if not h:
        return None
    return _fetch_account_balances(account_id, h)


# ── Transactions ──────────────────────────────────────────────────────

def fetch_transactions(
    account_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[Dict]:
    """Fetch transactions for an account from GoCardless.

    GET /accounts/{id}/transactions/?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
    Returns {transactions: {booked: [...], pending: [...]}}
    We return the booked transactions.
    """
    h = _auth_headers()
    if not h:
        return []

    params: Dict[str, str] = {}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to

    try:
        resp = requests.get(
            f"{GC_BASE}/accounts/{account_id}/transactions/",
            headers=h,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        txs = data.get("transactions", {})
        booked = txs.get("booked", [])
        return booked
    except Exception as e:
        print(f"[GoCardless] Transactions error ({account_id}): {e}")
        return []


# ── Transaction caching + delta sync ─────────────────────────────────

def sync_transactions(
    account_id: str,
    user_id: str = "_default",
    force_full: bool = False,
) -> List[Dict]:
    """Sync transactions with delta support. Returns all merged transactions."""
    udir = _user_cache_dir(user_id)
    cache_file = udir / f"transactions_{account_id}.json"
    cached = _load_json(cache_file)

    existing_txs: List[Dict] = []
    last_date: Optional[str] = None

    if cached and not force_full:
        existing_txs = cached.get("transactions", [])
        last_date = cached.get("last_sync_date")

    # Delta: overlap by 3 days to catch any late-settled transactions
    date_from = None
    if last_date and not force_full:
        dt = datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=3)
        date_from = dt.strftime("%Y-%m-%d")

    new_txs = fetch_transactions(account_id, date_from=date_from)

    # Merge & deduplicate
    seen_ids = set()
    merged = []
    for tx in existing_txs + new_txs:
        tx_id = (
            tx.get("transactionId")
            or tx.get("internalTransactionId")
            or tx.get("entryReference")
            or ""
        )
        if not tx_id:
            tx_id = hashlib.md5(
                json.dumps(tx, sort_keys=True, default=str).encode()
            ).hexdigest()
            tx["_generated_id"] = tx_id
        if tx_id not in seen_ids:
            seen_ids.add(tx_id)
            merged.append(tx)

    # Sort by date descending
    merged.sort(
        key=lambda t: t.get("bookingDate", t.get("valueDate", "1970-01-01")),
        reverse=True,
    )

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
    """Return locally cached transactions without API call."""
    udir = _user_cache_dir(user_id)
    cache_file = udir / f"transactions_{account_id}.json"
    cached = _load_json(cache_file)
    if cached:
        return cached.get("transactions", [])
    return []


# ── Transaction normalisation ────────────────────────────────────────

def normalize_transaction(tx: Dict) -> Dict:
    """Normalise a GoCardless (Berlin Group PSD2) transaction into a flat dict.

    GoCardless returns Berlin Group format:
      transactionAmount: {amount: "45.00", currency: "EUR"}
      bookingDate / valueDate
      creditorName / debtorName
      remittanceInformationUnstructured / remittanceInformationUnstructuredArray
    """
    # Amount
    amount_obj = tx.get("transactionAmount", {})
    if isinstance(amount_obj, dict):
        amount = float(amount_obj.get("amount", 0))
        currency = amount_obj.get("currency", "EUR")
    else:
        amount = float(amount_obj) if amount_obj else 0
        currency = "EUR"

    # Date
    date = tx.get("bookingDate", tx.get("valueDate", ""))

    # Counterparty
    counterparty = (
        tx.get("creditorName", "")
        or tx.get("debtorName", "")
        or tx.get("merchantName", "")
        or ""
    )

    # Description — may be string or array
    description = tx.get("remittanceInformationUnstructured", "")
    if not description:
        arr = tx.get("remittanceInformationUnstructuredArray", [])
        if arr:
            description = " | ".join(arr) if isinstance(arr, list) else str(arr)
    if not description:
        description = tx.get("additionalInformation", "")

    # Transaction ID
    tx_id = (
        tx.get("transactionId")
        or tx.get("internalTransactionId")
        or tx.get("entryReference")
        or tx.get("_generated_id", "")
    )

    return {
        "id": tx_id,
        "date": date,
        "amount": amount,
        "currency": currency,
        "counterparty": counterparty,
        "description": description,
        "category": tx.get("_category", ""),
        "rule_id": tx.get("_rule_id", ""),
        "raw": tx,
    }


# ── Transaction categorisation (OpenAI) ──────────────────────────────

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
    """Use OpenAI to categorise a batch of transactions."""
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
            "\n\nReturn ONLY a JSON array of objects with keys 'index' (int) and "
            "'category' (string). No commentary."
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


# ── Rules engine ─────────────────────────────────────────────────────

def load_rules(user_id: str) -> List[Dict]:
    udir = _user_cache_dir(user_id)
    return _load_json(udir / "rules.json") or []


def save_rules(user_id: str, rules: List[Dict]):
    udir = _user_cache_dir(user_id)
    _save_json(udir / "rules.json", rules)


def add_rule(
    user_id: str,
    name: str,
    counterparty_pattern: str,
    category: str,
    expected_amount: Optional[float] = None,
    amount_tolerance: float = 0.1,
    frequency_days: int = 30,
    rule_type: str = "recurring",
) -> Dict:
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
    rules = load_rules(user_id)
    rules = [r for r in rules if r["id"] != rule_id]
    save_rules(user_id, rules)


def apply_rules(transactions: List[Dict], rules: List[Dict]) -> List[Dict]:
    """Apply rules to transactions. Sets _category and _rule_id on matches."""
    active_rules = [r for r in rules if r.get("active", True)]
    for tx in transactions:
        if tx.get("_rule_id"):
            continue
        norm = normalize_transaction(tx)
        cp = norm["counterparty"].lower()
        desc = norm["description"].lower()
        for rule in active_rules:
            pattern = rule["counterparty_pattern"]
            if pattern and (pattern in cp or pattern in desc):
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


# ── Monitoring helpers ───────────────────────────────────────────────

def get_rule_matches(
    transactions: List[Dict],
    rule: Dict,
    months_back: int = 6,
) -> List[Dict]:
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
    summaries = []
    now = datetime.utcnow()

    for rule in rules:
        if not rule.get("active", True) or rule.get("rule_type") == "one-time":
            continue

        matches = get_rule_matches(transactions, rule, months_back)
        freq = rule.get("frequency_days", 30)
        expected_amount = rule.get("expected_amount")

        last_date = matches[-1]["date"] if matches else None

        window_days = months_back * 30
        expected_count = max(1, window_days // freq)
        actual_count = len(matches)
        cumulative = sum(m["amount"] for m in matches)

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


# ── Delete connection ────────────────────────────────────────────────

def delete_connection(connection_id: str, user_id: str):
    """Remove a connection from local cache.

    Also deletes the requisition on the GoCardless side (best-effort).
    """
    udir = _user_cache_dir(user_id)
    conns = _load_json(udir / "connections.json") or []

    # Try to delete the requisition remotely
    for c in conns:
        if c["id"] == connection_id and c.get("requisition_id"):
            h = _auth_headers()
            if h:
                try:
                    requests.delete(
                        f"{GC_BASE}/requisitions/{c['requisition_id']}/",
                        headers=h,
                        timeout=10,
                    )
                except Exception:
                    pass  # best-effort
            break

    conns = [c for c in conns if c["id"] != connection_id]
    _save_json(udir / "connections.json", conns)
