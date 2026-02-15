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

# Credentials are read dynamically from environment in get_credentials().
# Keep import-time values as fallback only.
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

def _save_json(path: Path, data: Any):
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


# ── Credential management ──────────────────────────────────────────────

def get_credentials() -> Tuple[str, str]:
    """Return (secret_id, secret_key) from environment variables."""
    sid = os.environ.get("GC_SECRET_ID") or GC_SECRET_ID
    skey = os.environ.get("GC_SECRET_KEY") or GC_SECRET_KEY
    return sid, skey


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
    normalized_country = (country or "DE").upper()
    cache_path = _CACHE_DIR / f"institutions_{normalized_country.lower()}.json"
    cached = _load_json(cache_path)
    if cached and cached.get("_ts", 0) > time.time() - 86400:
        return cached.get("data", [])

    h = _auth_headers()
    if not h:
        return cached.get("data", []) if cached else []

    def _extract_institutions(raw_data: Any) -> List[Dict[str, Any]]:
        if isinstance(raw_data, list):
            return raw_data
        if not isinstance(raw_data, dict):
            return []
        if isinstance(raw_data.get("results"), list):
            return raw_data.get("results", [])
        if isinstance(raw_data.get("data"), list):
            return raw_data.get("data", [])
        if isinstance(raw_data.get("institutions"), list):
            return raw_data.get("institutions", [])
        return []

    def _normalize(items: List[Dict[str, Any]], fallback_country: str) -> List[Dict[str, Any]]:
        normalised_items: List[Dict[str, Any]] = []
        for inst in items:
            inst_id = inst.get("id", "")
            inst_name = inst.get("name", "")
            if not inst_id or not inst_name:
                continue
            countries = inst.get("countries") or [fallback_country]
            normalised_items.append({
                "id": inst_id,
                "name": inst_name,
                "logo": inst.get("logo", ""),
                "countries": countries,
                "transaction_total_days": inst.get("transaction_total_days", "90"),
                "bic": inst.get("bic", ""),
            })
        return normalised_items

    try:
        query_candidates = [normalized_country]
        if normalized_country == "DE":
            query_candidates.extend(["de", "DEU"])

        for query_country in query_candidates:
            resp = requests.get(
                f"{GC_BASE}/institutions/",
                headers=h,
                params={"country": query_country},
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()
            institutions = _extract_institutions(raw)
            normalised = _normalize(institutions, normalized_country)
            if normalised:
                _save_json(cache_path, {"_ts": time.time(), "data": normalised})
                return normalised

        # Final fallback for Germany: request unfiltered list and filter by countries metadata
        if normalized_country == "DE":
            resp = requests.get(
                f"{GC_BASE}/institutions/",
                headers=h,
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()
            institutions = _extract_institutions(raw)
            filtered = []
            for inst in institutions:
                countries = inst.get("countries") or []
                countries_upper = [str(c).upper() for c in countries]
                if "DE" in countries_upper:
                    filtered.append(inst)
            normalised = _normalize(filtered, normalized_country)
            if normalised:
                _save_json(cache_path, {"_ts": time.time(), "data": normalised})
                return normalised

        # Keep behavior deterministic: return cached data if present, otherwise empty list
        return cached.get("data", []) if cached else []
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
    market: str = "DE",
    institution_id: Optional[str] = None,
) -> Optional[Dict]:
    """Create agreement + requisition via GoCardless API.

    Returns a connection dict (caller must persist client-side).
    Does NOT store any data on the server.
    """
    if not institution_id:
        return None

    agreement = create_agreement(institution_id)
    agreement_id = agreement["id"] if agreement else None

    reference = f"apex_{int(time.time())}"
    requisition = create_requisition(
        institution_id=institution_id,
        agreement_id=agreement_id,
        reference=reference,
    )
    if not requisition:
        return None

    return {
        "id": reference,
        "requisition_id": requisition.get("id", ""),
        "agreement_id": agreement_id,
        "institution_id": institution_id,
        "status": "CR",
        "link": requisition.get("link", ""),
        "created": datetime.utcnow().isoformat(),
        "market": market,
        "accounts": [],
    }


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


def complete_connection(requisition_id: str) -> Optional[Dict]:
    """Check requisition status via GoCardless API.

    Returns {status, accounts} or None on failure.
    Does NOT store any data on the server.
    """
    data = get_requisition_status(requisition_id)
    if not data:
        return None
    return {
        "status": data.get("status", ""),
        "accounts": data.get("accounts", []),
    }


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


def fetch_accounts(account_ids: List[str]) -> List[Dict]:
    """Fetch account details from GoCardless API for given account UUIDs.

    Calls /accounts/{id}/, /details/, /balances/ for each.
    Returns normalised list.  Does NOT store data on the server.
    """
    if not account_ids:
        return []
    h = _auth_headers()
    if not h:
        return []

    normalised: List[Dict] = []
    for aid in account_ids:
        meta = _fetch_account_metadata(aid, h)
        details = _fetch_account_details(aid, h)
        balances_raw = _fetch_account_balances(aid, h)

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
    existing_txs: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Fetch transactions from GoCardless and merge with existing ones.

    Uses delta sync (3-day overlap) when existing_txs is provided.
    Does NOT store any data on the server — caller must persist client-side.
    """
    existing_txs = existing_txs or []

    # Find last date from existing transactions for delta sync
    last_date: Optional[str] = None
    for tx in existing_txs:
        d = tx.get("bookingDate", tx.get("valueDate"))
        if d and (last_date is None or d > last_date):
            last_date = d

    date_from = None
    if last_date:
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

    merged.sort(
        key=lambda t: t.get("bookingDate", t.get("valueDate", "1970-01-01")),
        reverse=True,
    )
    return merged


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
    batch_size: int = 80,
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
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You categorise bank transactions. Be concise."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2000,
                temperature=0.1,
                timeout=30,
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


# ── Rules engine (pure functions — data lives in browser) ────────────

def make_rule(
    name: str,
    counterparty_pattern: str,
    category: str,
    expected_amount: Optional[float] = None,
    amount_tolerance: float = 0.1,
    frequency_days: int = 30,
    rule_type: str = "recurring",
) -> Dict:
    """Create a rule dict.  Caller stores it client-side."""
    return {
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
            match_categories = [c for c in (rule.get("match_categories") or []) if c]
            if match_categories and norm.get("category") not in match_categories:
                continue

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

        match_categories = [c for c in (rule.get("match_categories") or []) if c]
        if match_categories and norm.get("category") not in match_categories:
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
            "match_categories": rule.get("match_categories", []),
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


# ── Delete connection (remote cleanup only) ──────────────────────────

def delete_connection_remote(requisition_id: str):
    """Delete a requisition on the GoCardless side (best-effort).

    Caller removes the connection from client-side storage.
    """
    if not requisition_id:
        return
    h = _auth_headers()
    if h:
        try:
            requests.delete(
                f"{GC_BASE}/requisitions/{requisition_id}/",
                headers=h,
                timeout=10,
            )
        except Exception:
            pass
