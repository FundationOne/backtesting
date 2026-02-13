"""
Bank Account Sync Page
Connect bank accounts via GoCardless (PSD2 Open Banking),
sync transactions, categorise with AI, create recurring-transaction rules,
and monitor expected vs actual cash flows.
"""

import dash
from dash import html, dcc, Input, Output, State, ctx, no_update, dash_table, ALL, MATCH
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import json
from datetime import datetime, timedelta

from components.gocardless_api import (
    has_credentials,
    save_credentials,
    get_credentials,
    list_institutions,
    create_requisition,
    get_user_requisitions,
    refresh_requisition_status,
    sync_transactions,
    get_cached_transactions,
    get_account_details,
    get_account_balances,
    normalize_transaction,
    categorise_transactions_batch,
    load_default_categories,
    load_rules,
    save_rules,
    add_rule,
    delete_rule,
    apply_rules,
    compute_monitoring_summary,
    delete_requisition,
)

# ── Layout ──────────────────────────────────────────────────────────────

def _setup_card():
    """GoCardless credentials setup card (shown when not yet configured)."""
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.Div([
                    html.I(className="bi bi-bank2", style={"fontSize": "2.5rem", "color": "#3b82f6"}),
                ], className="text-center mb-3"),
                html.H5("Connect Your Bank", className="text-center mb-2"),
                html.P(
                    "Enter your GoCardless Bank Account Data credentials to get started. "
                    "Free tier supports up to 50 bank connections.",
                    className="text-center text-muted small mb-4",
                ),
                html.A(
                    "Get free API credentials →",
                    href="https://bankaccountdata.gocardless.com/signup",
                    target="_blank",
                    className="d-block text-center mb-4 small",
                ),
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Secret ID", className="small fw-semibold"),
                    dbc.Input(id="gc-secret-id", type="password", placeholder="your-secret-id",
                              className="mb-2", size="sm"),
                ], md=6),
                dbc.Col([
                    dbc.Label("Secret Key", className="small fw-semibold"),
                    dbc.Input(id="gc-secret-key", type="password", placeholder="your-secret-key",
                              className="mb-2", size="sm"),
                ], md=6),
            ]),
            dbc.Button(
                [html.I(className="bi bi-key me-2"), "Save & Connect"],
                id="gc-save-creds-btn",
                color="primary",
                className="w-100 mt-2",
                size="sm",
            ),
            html.Div(id="gc-creds-feedback", className="mt-2"),
        ])
    ], className="card-modern mb-4", style={"maxWidth": "520px", "margin": "0 auto"})


def _bank_selector_card():
    """Bank/institution search and selection."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-search me-2"),
            "Select Your Bank",
        ], className="card-header-modern"),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.InputGroup([
                        dbc.Input(
                            id="bank-search-input",
                            placeholder="Search banks (e.g. Sparkasse, N26, ING)...",
                            size="sm",
                        ),
                        dbc.Button(
                            html.I(className="bi bi-search"),
                            id="bank-search-btn",
                            color="primary",
                            size="sm",
                            n_clicks=0,
                        ),
                    ], size="sm"),
                ], md=8),
                dbc.Col([
                    dbc.Select(
                        id="bank-country-select",
                        options=[
                            {"label": "🇩🇪 Germany", "value": "DE"},
                            {"label": "🇦🇹 Austria", "value": "AT"},
                            {"label": "🇨🇭 Switzerland", "value": "CH"},
                            {"label": "🇳🇱 Netherlands", "value": "NL"},
                            {"label": "🇫🇷 France", "value": "FR"},
                            {"label": "🇬🇧 United Kingdom", "value": "GB"},
                        ],
                        value="DE",
                        size="sm",
                    ),
                ], md=4),
            ], className="mb-3"),
            html.Div(id="bank-search-results", children=[
                html.P("Search for your bank to get started.", className="text-muted small text-center py-3"),
            ]),
        ]),
    ], className="card-modern mb-4")


def _connected_accounts_card():
    """Shows connected bank accounts with balances."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-wallet2 me-2"),
            "Connected Accounts",
            dbc.Button(
                [html.I(className="bi bi-arrow-clockwise me-1"), "Refresh"],
                id="refresh-accounts-btn",
                color="link",
                size="sm",
                className="ms-auto p-0",
                n_clicks=0,
            ),
        ], className="card-header-modern"),
        dbc.CardBody(id="connected-accounts-body", children=[
            html.P("No accounts connected yet.", className="text-muted small text-center py-3"),
        ]),
    ], className="card-modern mb-4")


def _transactions_card():
    """Transaction list with categories."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-receipt me-2"),
            "Transactions",
            html.Div([
                dbc.Button(
                    [html.I(className="bi bi-arrow-clockwise me-1"), "Sync"],
                    id="sync-transactions-btn",
                    color="primary",
                    size="sm",
                    outline=True,
                    className="me-2",
                    n_clicks=0,
                ),
                dbc.Button(
                    [html.I(className="bi bi-robot me-1"), "AI Categorise"],
                    id="ai-categorise-btn",
                    color="info",
                    size="sm",
                    outline=True,
                    n_clicks=0,
                ),
            ], className="ms-auto d-flex"),
        ], className="card-header-modern"),
        dbc.CardBody([
            # Filters row
            dbc.Row([
                dbc.Col([
                    dbc.InputGroup([
                        dbc.InputGroupText(html.I(className="bi bi-funnel"), className="bg-transparent"),
                        dbc.Input(id="tx-filter-input", placeholder="Filter by name, category...", size="sm"),
                    ], size="sm"),
                ], md=4),
                dbc.Col([
                    dbc.Select(
                        id="tx-category-filter",
                        options=[{"label": "All Categories", "value": ""}],
                        value="",
                        size="sm",
                    ),
                ], md=3),
                dbc.Col([
                    dbc.Select(
                        id="tx-account-filter",
                        options=[{"label": "All Accounts", "value": ""}],
                        value="",
                        size="sm",
                    ),
                ], md=3),
                dbc.Col([
                    dbc.Select(
                        id="tx-direction-filter",
                        options=[
                            {"label": "All", "value": ""},
                            {"label": "Income ↑", "value": "in"},
                            {"label": "Expense ↓", "value": "out"},
                        ],
                        value="",
                        size="sm",
                    ),
                ], md=2),
            ], className="mb-3"),
            # Transactions container
            html.Div(id="transactions-container", children=[
                html.P("Connect a bank account and sync to see transactions.", className="text-muted small text-center py-4"),
            ]),
            html.Div(id="tx-sync-feedback", className="mt-2"),
        ]),
    ], className="card-modern mb-4")


def _rules_card():
    """Recurring transaction rules management."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-calendar-check me-2"),
            "Transaction Rules",
            dbc.Button(
                [html.I(className="bi bi-plus-lg me-1"), "New Rule"],
                id="open-add-rule-modal-btn",
                color="primary",
                size="sm",
                className="ms-auto",
                n_clicks=0,
            ),
        ], className="card-header-modern"),
        dbc.CardBody(id="rules-container", children=[
            html.P("No rules yet. Create rules to track recurring transactions.", className="text-muted small text-center py-3"),
        ]),
    ], className="card-modern mb-4")


def _monitoring_card():
    """Monitoring panel: expected vs actual transactions."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-clipboard-data me-2"),
            "Monitoring",
            dbc.Select(
                id="monitoring-months-select",
                options=[
                    {"label": "Last 3 months", "value": "3"},
                    {"label": "Last 6 months", "value": "6"},
                    {"label": "Last 12 months", "value": "12"},
                ],
                value="6",
                size="sm",
                style={"width": "160px"},
                className="ms-auto",
            ),
        ], className="card-header-modern"),
        dbc.CardBody(id="monitoring-container", children=[
            html.P("Create rules first, then check monitoring for expected vs actual.", className="text-muted small text-center py-3"),
        ]),
    ], className="card-modern mb-4")


def _add_rule_modal():
    """Modal for adding/editing a transaction rule."""
    categories = load_default_categories()
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle([
            html.I(className="bi bi-plus-circle me-2"),
            "Create Transaction Rule",
        ]), close_button=True),
        dbc.ModalBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Rule Name", className="small fw-semibold"),
                    dbc.Input(id="rule-name-input", placeholder="e.g. Netflix Subscription", size="sm"),
                ], md=6),
                dbc.Col([
                    dbc.Label("Category", className="small fw-semibold"),
                    dbc.Select(
                        id="rule-category-select",
                        options=[{"label": c, "value": c} for c in categories],
                        size="sm",
                    ),
                ], md=6),
            ], className="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Counterparty Pattern", className="small fw-semibold"),
                    dbc.Input(id="rule-pattern-input", placeholder="e.g. netflix, spotify...", size="sm"),
                    html.Small(
                        "Matched against transaction counterparty and description (case-insensitive).",
                        className="text-muted",
                    ),
                ], md=12),
            ], className="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Expected Amount (€)", className="small fw-semibold"),
                    dbc.Input(id="rule-amount-input", type="number", placeholder="e.g. 12.99",
                              size="sm", step="0.01"),
                ], md=4),
                dbc.Col([
                    dbc.Label("Tolerance (%)", className="small fw-semibold"),
                    dbc.Input(id="rule-tolerance-input", type="number", value=10,
                              size="sm", min=0, max=100, step=1),
                ], md=4),
                dbc.Col([
                    dbc.Label("Frequency", className="small fw-semibold"),
                    dbc.Select(
                        id="rule-frequency-select",
                        options=[
                            {"label": "Weekly", "value": "7"},
                            {"label": "Bi-weekly", "value": "14"},
                            {"label": "Monthly", "value": "30"},
                            {"label": "Quarterly", "value": "90"},
                            {"label": "Yearly", "value": "365"},
                        ],
                        value="30",
                        size="sm",
                    ),
                ], md=4),
            ]),
        ]),
        dbc.ModalFooter([
            html.Div(id="add-rule-feedback", className="me-auto"),
            dbc.Button("Cancel", id="cancel-rule-btn", color="secondary", size="sm", n_clicks=0),
            dbc.Button(
                [html.I(className="bi bi-check-lg me-1"), "Create Rule"],
                id="confirm-add-rule-btn",
                color="primary",
                size="sm",
                n_clicks=0,
            ),
        ]),
    ], id="add-rule-modal", is_open=False, centered=True, size="lg")


# ── Main layout ────────────────────────────────────────────────────────

layout = html.Div([
    # Stores
    dcc.Store(id="bs-connected-accounts", storage_type="local"),   # [{account_id, iban, name, requisition_id}]
    dcc.Store(id="bs-transactions-cache", storage_type="memory"),  # current session tx list
    dcc.Store(id="bs-active-requisition", storage_type="session"), # pending requisition id
    dcc.Store(id="bs-institutions-cache", storage_type="session"),

    # Page header
    html.Div([
        html.H4([
            html.I(className="bi bi-bank me-2"),
            "Bank Account Sync",
        ], className="page-title"),
        html.P("Connect your bank, categorise transactions, track recurring payments.", className="page-subtitle"),
    ], className="page-header"),

    # Setup (hidden once credentials are saved)
    html.Div(id="gc-setup-section", children=[_setup_card()]),

    # Main content (visible after setup)
    html.Div(id="gc-main-section", style={"display": "none"}, children=[
        dbc.Row([
            dbc.Col([
                _bank_selector_card(),
                _connected_accounts_card(),
            ], lg=4),
            dbc.Col([
                _transactions_card(),
            ], lg=8),
        ]),
        dbc.Row([
            dbc.Col([_rules_card()], lg=5),
            dbc.Col([_monitoring_card()], lg=7),
        ]),
    ]),

    _add_rule_modal(),
], className="p-4")


# ── Helpers ─────────────────────────────────────────────────────────────

def _institution_item(inst):
    """Render a single bank result row."""
    logo = inst.get("logo", "")
    name = inst.get("name", "Unknown")
    countries = ", ".join(inst.get("countries", []))
    inst_id = inst.get("id", "")

    logo_el = html.Img(
        src=logo, style={"width": "28px", "height": "28px", "objectFit": "contain"},
        className="me-3 rounded",
    ) if logo else html.I(className="bi bi-bank me-3", style={"fontSize": "1.4rem"})

    return html.Div([
        html.Div([
            logo_el,
            html.Div([
                html.Div(name, className="fw-semibold small"),
                html.Div(countries, className="text-muted", style={"fontSize": "0.7rem"}),
            ]),
        ], className="d-flex align-items-center"),
        dbc.Button(
            "Connect",
            id={"type": "connect-bank-btn", "index": inst_id},
            color="primary",
            size="sm",
            outline=True,
            n_clicks=0,
        ),
    ], className="d-flex align-items-center justify-content-between py-2 px-3 border-bottom")


def _account_item(acct):
    """Render a connected account row."""
    iban = acct.get("iban", "")
    name = acct.get("name", iban)
    balance = acct.get("balance")
    currency = acct.get("currency", "EUR")
    status = acct.get("status", "READY")

    masked_iban = f"****{iban[-4:]}" if len(iban) >= 4 else iban
    bal_str = f"{balance:,.2f} {currency}" if balance is not None else "—"

    status_color = "success" if status in ("READY", "LN") else "warning"

    return html.Div([
        html.Div([
            html.I(className="bi bi-credit-card me-2 text-primary"),
            html.Div([
                html.Div(name, className="fw-semibold small"),
                html.Div(masked_iban, className="text-muted", style={"fontSize": "0.7rem"}),
            ]),
        ], className="d-flex align-items-center"),
        html.Div([
            html.Span(bal_str, className="fw-semibold small me-2"),
            dbc.Badge(status, color=status_color, className="small"),
        ], className="d-flex align-items-center"),
    ], className="d-flex align-items-center justify-content-between py-2 px-3 border-bottom")


def _transaction_row(tx_norm, idx):
    """Render a single transaction row."""
    amount = tx_norm["amount"]
    is_income = amount > 0
    color = "#10b981" if is_income else "#ef4444"
    sign = "+" if is_income else ""
    amount_str = f"{sign}{amount:,.2f} {tx_norm['currency']}"

    cat = tx_norm.get("category", "")
    cat_badge = dbc.Badge(cat, color="light", text_color="dark", className="me-1") if cat else ""

    counterparty = tx_norm["counterparty"] or "—"
    desc_short = (tx_norm["description"][:80] + "…") if len(tx_norm["description"]) > 80 else tx_norm["description"]

    return html.Div([
        html.Div([
            html.Div([
                html.Span(tx_norm["date"], className="text-muted me-3", style={"fontSize": "0.75rem", "minWidth": "80px"}),
                html.Div([
                    html.Div(counterparty, className="fw-semibold small"),
                    html.Div(desc_short, className="text-muted", style={"fontSize": "0.7rem"}),
                ]),
            ], className="d-flex align-items-center"),
            html.Div([
                cat_badge,
                html.Span(amount_str, className="fw-semibold small", style={"color": color}),
            ], className="d-flex align-items-center"),
        ], className="d-flex align-items-center justify-content-between"),
    ], className="py-2 px-3 border-bottom tx-row")


def _rule_item(rule):
    """Render a rule pill."""
    freq_map = {"7": "Weekly", "14": "Bi-weekly", "30": "Monthly", "90": "Quarterly", "365": "Yearly"}
    freq_label = freq_map.get(str(rule.get("frequency_days", 30)), f"Every {rule['frequency_days']}d")
    amt_str = f"€{abs(rule.get('expected_amount', 0)):,.2f}" if rule.get("expected_amount") else "Any amount"

    return html.Div([
        html.Div([
            html.I(className="bi bi-arrow-repeat me-2 text-primary"),
            html.Div([
                html.Div(rule["name"], className="fw-semibold small"),
                html.Div([
                    dbc.Badge(rule.get("category", ""), color="light", text_color="dark", className="me-1"),
                    html.Span(f"{freq_label} • {amt_str}", className="text-muted", style={"fontSize": "0.7rem"}),
                ], className="d-flex align-items-center mt-1"),
            ]),
        ], className="d-flex align-items-center"),
        dbc.Button(
            html.I(className="bi bi-trash"),
            id={"type": "delete-rule-btn", "index": rule["id"]},
            color="danger",
            size="sm",
            outline=True,
            n_clicks=0,
        ),
    ], className="d-flex align-items-center justify-content-between py-2 px-3 border-bottom")


def _monitoring_row(summary):
    """Render a monitoring summary row for a rule."""
    status = summary["status"]
    status_colors = {"OK": "success", "OVERDUE": "warning", "MISSING": "danger"}
    status_icon = {"OK": "bi-check-circle-fill", "OVERDUE": "bi-exclamation-triangle-fill",
                   "MISSING": "bi-x-circle-fill"}

    expected_total = 0
    if summary["expected_amount"] is not None:
        expected_total = abs(summary["expected_amount"]) * summary["expected_count"]

    return html.Div([
        html.Div([
            html.I(className=f"bi {status_icon.get(status, 'bi-question-circle')} me-2",
                   style={"color": {"OK": "#10b981", "OVERDUE": "#f59e0b", "MISSING": "#ef4444"}.get(status, "#6c757d")}),
            html.Div([
                html.Div(summary["name"], className="fw-semibold small"),
                html.Div([
                    dbc.Badge(summary["category"], color="light", text_color="dark", className="me-1"),
                    html.Span(
                        f"Last: {summary['last_date'] or 'Never'}",
                        className="text-muted", style={"fontSize": "0.7rem"},
                    ),
                ], className="d-flex align-items-center mt-1"),
            ]),
        ], className="d-flex align-items-center"),
        html.Div([
            html.Div([
                html.Span(f"{summary['actual_count']}", className="fw-bold"),
                html.Span(f"/{summary['expected_count']}", className="text-muted small"),
            ], className="text-center me-3"),
            html.Div([
                html.Div(f"€{abs(summary['cumulative']):,.2f}", className="small fw-semibold"),
                html.Div(
                    f"exp. €{expected_total:,.2f}" if expected_total else "",
                    className="text-muted", style={"fontSize": "0.7rem"},
                ),
            ], className="text-end me-3"),
            dbc.Badge(status, color=status_colors.get(status, "secondary")),
        ], className="d-flex align-items-center"),
    ], className="d-flex align-items-center justify-content-between py-2 px-3 border-bottom")


# ── Callbacks ───────────────────────────────────────────────────────────

def register_callbacks(app):
    # ── 1. Show/hide setup vs main section based on credentials ──────
    @app.callback(
        [Output("gc-setup-section", "style"),
         Output("gc-main-section", "style")],
        [Input("url", "pathname"),
         Input("gc-creds-feedback", "children")],
    )
    def toggle_sections(pathname, _feedback):
        if pathname != "/banksync":
            raise PreventUpdate
        if has_credentials():
            return {"display": "none"}, {"display": "block"}
        return {"display": "block"}, {"display": "none"}

    # ── 2. Save GoCardless credentials ───────────────────────────────
    @app.callback(
        Output("gc-creds-feedback", "children"),
        Input("gc-save-creds-btn", "n_clicks"),
        [State("gc-secret-id", "value"),
         State("gc-secret-key", "value")],
        prevent_initial_call=True,
    )
    def save_gc_creds(n, sid, skey):
        if not n:
            raise PreventUpdate
        if not sid or not skey:
            return dbc.Alert("Please enter both Secret ID and Secret Key.", color="warning", className="small py-1 mb-0")
        save_credentials(sid, skey)
        return dbc.Alert("Credentials saved! Searching for banks...", color="success", className="small py-1 mb-0")

    # ── 3. Search banks ──────────────────────────────────────────────
    @app.callback(
        Output("bank-search-results", "children"),
        [Input("bank-search-btn", "n_clicks"),
         Input("bank-search-input", "n_submit")],
        [State("bank-search-input", "value"),
         State("bank-country-select", "value")],
        prevent_initial_call=True,
    )
    def search_banks(n_clicks, n_submit, query, country):
        if not has_credentials():
            return dbc.Alert("Set up GoCardless credentials first.", color="warning", className="small py-1")

        institutions = list_institutions(country or "DE")
        if not institutions:
            return dbc.Alert("Could not load banks. Check your credentials.", color="danger", className="small py-1")

        # Filter by query
        if query:
            q = query.lower()
            institutions = [i for i in institutions if q in i.get("name", "").lower()]

        if not institutions:
            return html.P("No banks found matching your search.", className="text-muted small text-center py-3")

        # Show max 20 results
        items = [_institution_item(inst) for inst in institutions[:20]]
        return html.Div(items, style={"maxHeight": "350px", "overflowY": "auto"})

    # ── 4. Connect to a bank (create requisition) ────────────────────
    @app.callback(
        [Output("bs-active-requisition", "data"),
         Output("bank-search-results", "children", allow_duplicate=True)],
        Input({"type": "connect-bank-btn", "index": ALL}, "n_clicks"),
        State("current-user-store", "data"),
        prevent_initial_call=True,
    )
    def connect_bank(n_clicks_list, user_id):
        if not any(n_clicks_list):
            raise PreventUpdate

        triggered = ctx.triggered_id
        if not triggered or not isinstance(triggered, dict):
            raise PreventUpdate

        inst_id = triggered["index"]
        uid = user_id or "_default"

        req = create_requisition(inst_id, user_id=uid)
        if not req:
            return no_update, dbc.Alert(
                "Failed to create bank connection. Check credentials.",
                color="danger", className="small py-1",
            )

        link = req.get("link", "")
        req_id = req.get("id", "")

        msg = html.Div([
            dbc.Alert([
                html.I(className="bi bi-box-arrow-up-right me-2"),
                html.Strong("Bank authentication required"),
                html.P([
                    "Click the link below to authenticate with your bank. ",
                    "After completing authentication, click ",
                    html.Strong("'Check Status'"), " below.",
                ], className="mb-2 small"),
                html.A(
                    [html.I(className="bi bi-bank me-1"), "Authenticate with your bank →"],
                    href=link,
                    target="_blank",
                    className="btn btn-primary btn-sm",
                ),
                html.Hr(className="my-2"),
                dbc.Button(
                    [html.I(className="bi bi-arrow-clockwise me-1"), "Check Status"],
                    id="check-requisition-btn",
                    color="success",
                    size="sm",
                    n_clicks=0,
                ),
                html.Div(id="requisition-status-feedback", className="mt-2"),
            ], color="info", className="mt-3"),
        ])
        return req_id, msg

    # ── 5. Check requisition status after bank auth ──────────────────
    @app.callback(
        [Output("connected-accounts-body", "children", allow_duplicate=True),
         Output("requisition-status-feedback", "children")],
        Input("check-requisition-btn", "n_clicks"),
        [State("bs-active-requisition", "data"),
         State("current-user-store", "data")],
        prevent_initial_call=True,
    )
    def check_requisition_status(n, req_id, user_id):
        if not n or not req_id:
            raise PreventUpdate

        uid = user_id or "_default"
        status = refresh_requisition_status(req_id, uid)

        if status == "LN":
            # Linked! Fetch account details
            reqs = get_user_requisitions(uid)
            accounts = []
            for r in reqs:
                if r["id"] == req_id:
                    for acct_id in r.get("accounts", []):
                        details = get_account_details(acct_id)
                        balances = get_account_balances(acct_id)
                        bal = None
                        currency = "EUR"
                        if balances:
                            for b in balances:
                                if b.get("balanceType") in ("closingBooked", "interimAvailable", "expected"):
                                    bal = float(b.get("balanceAmount", {}).get("amount", 0))
                                    currency = b.get("balanceAmount", {}).get("currency", "EUR")
                                    break
                        acct_info = {
                            "account_id": acct_id,
                            "iban": (details or {}).get("iban", ""),
                            "name": (details or {}).get("ownerName", (details or {}).get("product", acct_id)),
                            "balance": bal,
                            "currency": currency,
                            "requisition_id": req_id,
                            "status": "READY",
                        }
                        accounts.append(acct_info)
                    break

            if accounts:
                items = [_account_item(a) for a in accounts]
                return html.Div(items), dbc.Alert("Bank connected successfully!", color="success", className="small py-1 mb-0")
            return no_update, dbc.Alert("Connected but found no accounts.", color="warning", className="small py-1 mb-0")

        elif status == "CR":
            return no_update, dbc.Alert("Awaiting bank authentication. Please complete the bank login first.", color="info", className="small py-1 mb-0")
        elif status == "EX":
            return no_update, dbc.Alert("Link expired. Please try connecting again.", color="danger", className="small py-1 mb-0")
        elif status == "RJ":
            return no_update, dbc.Alert("Connection rejected by the bank.", color="danger", className="small py-1 mb-0")
        else:
            return no_update, dbc.Alert(f"Status: {status}. Try again shortly.", color="info", className="small py-1 mb-0")

    # ── 6. Refresh connected accounts ────────────────────────────────
    @app.callback(
        Output("connected-accounts-body", "children"),
        [Input("refresh-accounts-btn", "n_clicks"),
         Input("url", "pathname")],
        State("current-user-store", "data"),
    )
    def refresh_accounts(n, pathname, user_id):
        if pathname != "/banksync":
            raise PreventUpdate

        uid = user_id or "_default"
        reqs = get_user_requisitions(uid)

        if not reqs:
            return html.P("No accounts connected yet.", className="text-muted small text-center py-3")

        accounts = []
        for r in reqs:
            for acct_id in r.get("accounts", []):
                accounts.append({
                    "account_id": acct_id,
                    "iban": "",
                    "name": acct_id[:12] + "...",
                    "balance": None,
                    "currency": "EUR",
                    "requisition_id": r["id"],
                    "status": r.get("status", "—"),
                })

        if not accounts:
            return html.P("No accounts found. Connect a bank first.", className="text-muted small text-center py-3")

        return html.Div([_account_item(a) for a in accounts])

    # ── 7. Sync transactions ─────────────────────────────────────────
    @app.callback(
        [Output("transactions-container", "children"),
         Output("tx-sync-feedback", "children"),
         Output("bs-transactions-cache", "data"),
         Output("tx-category-filter", "options"),
         Output("tx-account-filter", "options")],
        [Input("sync-transactions-btn", "n_clicks"),
         Input("tx-filter-input", "value"),
         Input("tx-category-filter", "value"),
         Input("tx-account-filter", "value"),
         Input("tx-direction-filter", "value")],
        [State("current-user-store", "data"),
         State("bs-transactions-cache", "data"),
         State("api_key_store", "data")],
        prevent_initial_call=True,
    )
    def sync_and_filter_transactions(
        sync_clicks, filter_text, cat_filter, acct_filter, dir_filter,
        user_id, cached_txs, api_key_data,
    ):
        uid = user_id or "_default"
        triggered = ctx.triggered_id

        all_txs = cached_txs or []
        feedback = no_update

        # If sync button clicked, actually sync from API
        if triggered == "sync-transactions-btn" and sync_clicks:
            reqs = get_user_requisitions(uid)
            all_txs = []
            synced_accounts = 0
            for r in reqs:
                for acct_id in r.get("accounts", []):
                    txs = sync_transactions(acct_id, uid)
                    # Apply saved rules
                    rules = load_rules(uid)
                    txs = apply_rules(txs, rules)
                    all_txs.extend(txs)
                    synced_accounts += 1

            if synced_accounts == 0:
                feedback = dbc.Alert("No accounts to sync. Connect a bank first.", color="warning", className="small py-1 mb-0")
            else:
                feedback = dbc.Alert(
                    f"Synced {len(all_txs)} transactions from {synced_accounts} account(s).",
                    color="success", className="small py-1 mb-0",
                )

        if not all_txs:
            return (
                html.P("No transactions yet. Sync to load.", className="text-muted small text-center py-4"),
                feedback,
                all_txs,
                [{"label": "All Categories", "value": ""}],
                [{"label": "All Accounts", "value": ""}],
            )

        # Normalise for display
        normalised = [normalize_transaction(tx) for tx in all_txs]

        # Build filter options from data
        cats = sorted(set(n["category"] for n in normalised if n["category"]))
        cat_options = [{"label": "All Categories", "value": ""}] + [{"label": c, "value": c} for c in cats]

        acct_ids = sorted(set(tx.get("_account_id", "") for tx in all_txs if tx.get("_account_id")))
        acct_options = [{"label": "All Accounts", "value": ""}] + [{"label": a[:12], "value": a} for a in acct_ids]

        # Apply filters
        filtered = normalised
        if filter_text:
            q = filter_text.lower()
            filtered = [n for n in filtered if q in n["counterparty"].lower() or q in n["description"].lower() or q in n.get("category", "").lower()]
        if cat_filter:
            filtered = [n for n in filtered if n.get("category") == cat_filter]
        if dir_filter == "in":
            filtered = [n for n in filtered if n["amount"] > 0]
        elif dir_filter == "out":
            filtered = [n for n in filtered if n["amount"] < 0]

        # Render (max 200 rows)
        if not filtered:
            rows = html.P("No transactions match your filters.", className="text-muted small text-center py-3")
        else:
            rows = html.Div(
                [_transaction_row(n, i) for i, n in enumerate(filtered[:200])],
                style={"maxHeight": "500px", "overflowY": "auto"},
            )
            if len(filtered) > 200:
                rows = html.Div([
                    rows,
                    html.P(f"Showing 200 of {len(filtered)} transactions.", className="text-muted small text-center mt-2"),
                ])

        return rows, feedback, all_txs, cat_options, acct_options

    # ── 8. AI categorise ─────────────────────────────────────────────
    @app.callback(
        [Output("transactions-container", "children", allow_duplicate=True),
         Output("tx-sync-feedback", "children", allow_duplicate=True),
         Output("bs-transactions-cache", "data", allow_duplicate=True)],
        Input("ai-categorise-btn", "n_clicks"),
        [State("bs-transactions-cache", "data"),
         State("api_key_store", "data"),
         State("current-user-store", "data")],
        prevent_initial_call=True,
    )
    def ai_categorise(n, cached_txs, api_key_data, user_id):
        if not n or not cached_txs:
            raise PreventUpdate

        api_key = (api_key_data or {}).get("api_key", "")
        if not api_key:
            return no_update, dbc.Alert(
                [html.I(className="bi bi-exclamation-triangle me-1"),
                 "Set your OpenAI API key in Settings first."],
                color="warning", className="small py-1 mb-0",
            ), no_update

        uid = user_id or "_default"

        # Categorise uncategorised transactions
        uncategorised_count = sum(1 for tx in cached_txs if not tx.get("_category"))
        if uncategorised_count == 0:
            return no_update, dbc.Alert(
                "All transactions are already categorised!",
                color="info", className="small py-1 mb-0",
            ), no_update

        try:
            cached_txs = categorise_transactions_batch(cached_txs, api_key)
        except Exception as e:
            err_str = str(e)
            if "invalid_api_key" in err_str or "401" in err_str:
                msg = "Invalid OpenAI API key. Check your key in Settings."
            else:
                msg = f"Categorisation error: {err_str[:100]}"
            return no_update, dbc.Alert(msg, color="danger", className="small py-1 mb-0"), no_update

        categorised_count = uncategorised_count - sum(1 for tx in cached_txs if not tx.get("_category"))

        # Re-render transactions
        normalised = [normalize_transaction(tx) for tx in cached_txs]
        rows = html.Div(
            [_transaction_row(n, i) for i, n in enumerate(normalised[:200])],
            style={"maxHeight": "500px", "overflowY": "auto"},
        )

        feedback = dbc.Alert(
            f"Categorised {categorised_count} transactions using AI.",
            color="success", className="small py-1 mb-0",
        )

        return rows, feedback, cached_txs

    # ── 9. Open/close add-rule modal ─────────────────────────────────
    @app.callback(
        Output("add-rule-modal", "is_open"),
        [Input("open-add-rule-modal-btn", "n_clicks"),
         Input("cancel-rule-btn", "n_clicks"),
         Input("confirm-add-rule-btn", "n_clicks")],
        State("add-rule-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_rule_modal(open_n, cancel_n, confirm_n, is_open):
        t = ctx.triggered_id
        if t == "open-add-rule-modal-btn":
            return True
        if t in ("cancel-rule-btn", "confirm-add-rule-btn"):
            return False
        return is_open

    # ── 10. Create a new rule ────────────────────────────────────────
    @app.callback(
        [Output("rules-container", "children", allow_duplicate=True),
         Output("add-rule-feedback", "children")],
        Input("confirm-add-rule-btn", "n_clicks"),
        [State("rule-name-input", "value"),
         State("rule-category-select", "value"),
         State("rule-pattern-input", "value"),
         State("rule-amount-input", "value"),
         State("rule-tolerance-input", "value"),
         State("rule-frequency-select", "value"),
         State("current-user-store", "data")],
        prevent_initial_call=True,
    )
    def create_rule(n, name, category, pattern, amount, tolerance, freq, user_id):
        if not n:
            raise PreventUpdate
        if not name or not pattern:
            return no_update, dbc.Alert("Name and pattern are required.", color="warning", className="small py-1 mb-0")

        uid = user_id or "_default"
        expected_amount = float(amount) if amount else None
        tol = float(tolerance) / 100 if tolerance else 0.1
        freq_days = int(freq) if freq else 30

        add_rule(uid, name, pattern, category or "Other", expected_amount, tol, freq_days)

        # Refresh rules display
        rules = load_rules(uid)
        items = [_rule_item(r) for r in rules]
        return html.Div(items) if items else html.P("No rules.", className="text-muted small text-center py-3"), ""

    # ── 11. Delete a rule ────────────────────────────────────────────
    @app.callback(
        Output("rules-container", "children"),
        Input({"type": "delete-rule-btn", "index": ALL}, "n_clicks"),
        State("current-user-store", "data"),
        prevent_initial_call=True,
    )
    def remove_rule(n_clicks_list, user_id):
        if not any(n_clicks_list):
            raise PreventUpdate

        triggered = ctx.triggered_id
        if not triggered or not isinstance(triggered, dict):
            raise PreventUpdate

        uid = user_id or "_default"
        rule_id = triggered["index"]
        delete_rule(uid, rule_id)

        rules = load_rules(uid)
        if not rules:
            return html.P("No rules yet.", className="text-muted small text-center py-3")
        return html.Div([_rule_item(r) for r in rules])

    # ── 12. Refresh rules on page load ───────────────────────────────
    @app.callback(
        Output("rules-container", "children", allow_duplicate=True),
        Input("url", "pathname"),
        State("current-user-store", "data"),
        prevent_initial_call=True,
    )
    def load_rules_on_page(pathname, user_id):
        if pathname != "/banksync":
            raise PreventUpdate
        uid = user_id or "_default"
        rules = load_rules(uid)
        if not rules:
            return html.P("No rules yet. Create rules to track recurring transactions.", className="text-muted small text-center py-3")
        return html.Div([_rule_item(r) for r in rules])

    # ── 13. Monitoring panel ─────────────────────────────────────────
    @app.callback(
        Output("monitoring-container", "children"),
        [Input("monitoring-months-select", "value"),
         Input("rules-container", "children"),
         Input("bs-transactions-cache", "data")],
        State("current-user-store", "data"),
    )
    def update_monitoring(months, _rules_ui, cached_txs, user_id):
        uid = user_id or "_default"
        rules = load_rules(uid)
        txs = cached_txs or []

        if not rules or not txs:
            return html.P("Create rules and sync transactions to see monitoring.", className="text-muted small text-center py-3")

        months_back = int(months) if months else 6
        summaries = compute_monitoring_summary(txs, rules, months_back)

        if not summaries:
            return html.P("No recurring rules to monitor.", className="text-muted small text-center py-3")

        # Summary stats at top
        ok_count = sum(1 for s in summaries if s["status"] == "OK")
        overdue_count = sum(1 for s in summaries if s["status"] == "OVERDUE")
        missing_count = sum(1 for s in summaries if s["status"] == "MISSING")
        total_cumulative = sum(abs(s["cumulative"]) for s in summaries)

        stats = dbc.Row([
            dbc.Col([
                html.Div([
                    html.Div(str(ok_count), className="fs-4 fw-bold text-success"),
                    html.Div("On Track", className="text-muted small"),
                ], className="text-center"),
            ], width=3),
            dbc.Col([
                html.Div([
                    html.Div(str(overdue_count), className="fs-4 fw-bold text-warning"),
                    html.Div("Overdue", className="text-muted small"),
                ], className="text-center"),
            ], width=3),
            dbc.Col([
                html.Div([
                    html.Div(str(missing_count), className="fs-4 fw-bold text-danger"),
                    html.Div("Missing", className="text-muted small"),
                ], className="text-center"),
            ], width=3),
            dbc.Col([
                html.Div([
                    html.Div(f"€{total_cumulative:,.0f}", className="fs-4 fw-bold"),
                    html.Div("Cumulative", className="text-muted small"),
                ], className="text-center"),
            ], width=3),
        ], className="mb-3 py-2 bg-light rounded")

        rows = html.Div([_monitoring_row(s) for s in summaries])

        return html.Div([stats, rows])
