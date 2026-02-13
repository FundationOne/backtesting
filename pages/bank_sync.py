"""
Bank Account Sync Page
Connect bank accounts via GoCardless Bank Account Data (PSD2 Open Banking),
sync transactions, categorise with AI, create recurring-transaction rules,
and monitor expected vs actual cash flows.
"""

import dash
from dash import html, dcc, Input, Output, State, ctx, no_update, ALL
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import json
from datetime import datetime, timedelta

from components.bank_api import (
    has_credentials,
    list_institutions,
    create_connection,
    complete_connection,
    get_user_connections,
    fetch_accounts,
    sync_transactions,
    get_cached_transactions,
    normalize_transaction,
    categorise_transactions_batch,
    load_default_categories,
    load_rules,
    save_rules,
    add_rule,
    delete_rule,
    apply_rules,
    compute_monitoring_summary,
    delete_connection,
)

# ── Layout ──────────────────────────────────────────────────────────────

def _setup_card():
    """Shown when GoCardless credentials are not configured server-side."""
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.I(className="bi bi-exclamation-triangle",
                       style={"fontSize": "2.5rem", "color": "#f59e0b"}),
            ], className="text-center mb-3"),
            html.H5("Bank Sync Not Available", className="text-center mb-2"),
            html.P(
                "Bank account sync is not configured on this server. "
                "The administrator needs to set GC_SECRET_ID and GC_SECRET_KEY "
                "environment variables to enable PSD2 Open Banking connections.",
                className="text-center text-muted small mb-0",
            ),
        ])
    ], className="card-modern mb-4", style={"maxWidth": "520px", "margin": "0 auto"})


def _bank_connect_card():
    """Bank connection via GoCardless requisition flow."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-link-45deg me-2"),
            "Connect Bank Account",
        ], className="card-header-modern"),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Country", className="small fw-semibold"),
                    dbc.Select(
                        id="bank-country-select",
                        options=[
                            {"label": "🇩🇪 Germany", "value": "DE"},
                            {"label": "🇦🇹 Austria", "value": "AT"},
                            {"label": "🇨🇭 Switzerland", "value": "CH"},
                            {"label": "🇳🇱 Netherlands", "value": "NL"},
                            {"label": "🇫🇷 France", "value": "FR"},
                            {"label": "🇬🇧 United Kingdom", "value": "GB"},
                            {"label": "🇸🇪 Sweden", "value": "SE"},
                            {"label": "🇪🇸 Spain", "value": "ES"},
                            {"label": "🇮🇹 Italy", "value": "IT"},
                            {"label": "🇧🇪 Belgium", "value": "BE"},
                            {"label": "🇵🇱 Poland", "value": "PL"},
                            {"label": "🇩🇰 Denmark", "value": "DK"},
                            {"label": "🇳🇴 Norway", "value": "NO"},
                            {"label": "🇫🇮 Finland", "value": "FI"},
                            {"label": "🇮🇪 Ireland", "value": "IE"},
                            {"label": "🇵🇹 Portugal", "value": "PT"},
                        ],
                        value="DE",
                        size="sm",
                    ),
                ], md=4),
                dbc.Col([
                    dbc.Label("Bank", className="small fw-semibold"),
                    dbc.Select(
                        id="bank-institution-select",
                        options=[{"label": "Select country first…", "value": ""}],
                        value="",
                        size="sm",
                    ),
                ], md=5),
                dbc.Col([
                    dbc.Label(" ", className="small"),
                    dbc.Button(
                        [html.I(className="bi bi-bank me-2"), "Connect"],
                        id="connect-bank-btn",
                        color="primary",
                        className="w-100",
                        size="sm",
                        n_clicks=0,
                    ),
                ], md=3, className="d-flex align-items-end"),
            ], className="mb-3"),
            html.Div(id="bank-connect-feedback", children=[
                html.P([
                    html.I(className="bi bi-info-circle me-2"),
                    "Select your country and bank, then click 'Connect' to open "
                    "your bank's secure login via GoCardless. "
                    "After authenticating, you'll be redirected back here.",
                ], className="text-muted small mb-0"),
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
            html.Div(id="transactions-container", children=[
                html.P("Connect a bank account and sync to see transactions.",
                       className="text-muted small text-center py-4"),
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
            html.P("No rules yet. Create rules to track recurring transactions.",
                   className="text-muted small text-center py-3"),
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
            html.P("Create rules first, then check monitoring for expected vs actual.",
                   className="text-muted small text-center py-3"),
        ]),
    ], className="card-modern mb-4")


def _add_rule_modal():
    """Modal for adding a transaction rule."""
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
    dcc.Store(id="bs-connected-accounts", storage_type="local"),
    dcc.Store(id="bs-transactions-cache", storage_type="memory"),
    dcc.Store(id="bs-active-requisition", storage_type="session"),

    html.Div([
        html.H4([
            html.I(className="bi bi-bank me-2"),
            "Bank Account Sync",
        ], className="page-title"),
        html.P("Connect your bank, categorise transactions, track recurring payments.",
               className="page-subtitle"),
    ], className="page-header"),

    html.Div(id="gc-setup-section", children=[_setup_card()]),

    html.Div(id="gc-main-section", style={"display": "none"}, children=[
        dbc.Row([
            dbc.Col([
                _bank_connect_card(),
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


# ── Render helpers ──────────────────────────────────────────────────────

def _account_item(acct):
    iban = acct.get("iban", "")
    name = acct.get("name", iban)
    balance = acct.get("balance")
    currency = acct.get("currency", "EUR")
    status = acct.get("status", "READY")
    masked_iban = f"****{iban[-4:]}" if len(iban) >= 4 else iban
    bal_str = f"{balance:,.2f} {currency}" if balance is not None else "—"
    status_color = "success" if status in ("READY", "LINKED") else "warning"

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
                html.Span(tx_norm["date"], className="text-muted me-3",
                          style={"fontSize": "0.75rem", "minWidth": "80px"}),
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
    freq_map = {"7": "Weekly", "14": "Bi-weekly", "30": "Monthly",
                "90": "Quarterly", "365": "Yearly"}
    freq_label = freq_map.get(str(rule.get("frequency_days", 30)),
                              f"Every {rule['frequency_days']}d")
    amt_str = (f"€{abs(rule.get('expected_amount', 0)):,.2f}"
               if rule.get("expected_amount") else "Any amount")

    return html.Div([
        html.Div([
            html.I(className="bi bi-arrow-repeat me-2 text-primary"),
            html.Div([
                html.Div(rule["name"], className="fw-semibold small"),
                html.Div([
                    dbc.Badge(rule.get("category", ""), color="light",
                              text_color="dark", className="me-1"),
                    html.Span(f"{freq_label} • {amt_str}", className="text-muted",
                              style={"fontSize": "0.7rem"}),
                ], className="d-flex align-items-center mt-1"),
            ]),
        ], className="d-flex align-items-center"),
        dbc.Button(
            html.I(className="bi bi-trash"),
            id={"type": "delete-rule-btn", "index": rule["id"]},
            color="danger", size="sm", outline=True, n_clicks=0,
        ),
    ], className="d-flex align-items-center justify-content-between py-2 px-3 border-bottom")


def _monitoring_row(summary):
    status = summary["status"]
    status_colors = {"OK": "success", "OVERDUE": "warning", "MISSING": "danger"}
    status_icon = {"OK": "bi-check-circle-fill", "OVERDUE": "bi-exclamation-triangle-fill",
                   "MISSING": "bi-x-circle-fill"}
    status_clr = {"OK": "#10b981", "OVERDUE": "#f59e0b", "MISSING": "#ef4444"}
    expected_total = 0
    if summary["expected_amount"] is not None:
        expected_total = abs(summary["expected_amount"]) * summary["expected_count"]

    return html.Div([
        html.Div([
            html.I(className=f"bi {status_icon.get(status, 'bi-question-circle')} me-2",
                   style={"color": status_clr.get(status, "#6c757d")}),
            html.Div([
                html.Div(summary["name"], className="fw-semibold small"),
                html.Div([
                    dbc.Badge(summary["category"], color="light",
                              text_color="dark", className="me-1"),
                    html.Span(f"Last: {summary['last_date'] or 'Never'}",
                              className="text-muted", style={"fontSize": "0.7rem"}),
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
                html.Div(f"exp. €{expected_total:,.2f}" if expected_total else "",
                         className="text-muted", style={"fontSize": "0.7rem"}),
            ], className="text-end me-3"),
            dbc.Badge(status, color=status_colors.get(status, "secondary")),
        ], className="d-flex align-items-center"),
    ], className="d-flex align-items-center justify-content-between py-2 px-3 border-bottom")


# ── Callbacks ───────────────────────────────────────────────────────────

def register_callbacks(app):

    # 1. Show/hide setup vs main section
    @app.callback(
        [Output("gc-setup-section", "style"),
         Output("gc-main-section", "style")],
        Input("url", "pathname"),
    )
    def toggle_sections(pathname):
        if pathname != "/banksync":
            raise PreventUpdate
        if has_credentials():
            return {"display": "none"}, {"display": "block"}
        return {"display": "block"}, {"display": "none"}

    # 2. Load institutions when country changes
    @app.callback(
        Output("bank-institution-select", "options"),
        Input("bank-country-select", "value"),
        prevent_initial_call=True,
    )
    def load_institutions_for_country(country):
        if not country or not has_credentials():
            return [{"label": "Bank sync not configured", "value": ""}]
        institutions = list_institutions(country)
        if not institutions:
            return [{"label": "No banks found for this country", "value": ""}]
        options = [{"label": f"{inst['name']}", "value": inst["id"]}
                   for inst in sorted(institutions, key=lambda i: i["name"])]
        return options

    # 3. Connect bank (create agreement + requisition → redirect link)
    @app.callback(
        [Output("bank-connect-feedback", "children"),
         Output("bs-active-requisition", "data")],
        Input("connect-bank-btn", "n_clicks"),
        [State("bank-country-select", "value"),
         State("bank-institution-select", "value"),
         State("current-user-store", "data")],
        prevent_initial_call=True,
    )
    def start_bank_connection(n, country, institution_id, user_id):
        if not n:
            raise PreventUpdate
        if not has_credentials():
            return dbc.Alert("Set up GoCardless credentials first.",
                             color="warning", className="small py-1"), no_update
        if not institution_id:
            return dbc.Alert("Please select a bank first.",
                             color="warning", className="small py-1"), no_update

        uid = user_id or "_default"
        conn = create_connection(uid, market=country or "DE",
                                 institution_id=institution_id)
        if not conn:
            return dbc.Alert("Failed to create bank connection. Check credentials.",
                             color="danger", className="small py-1"), no_update

        link = conn.get("link", "")
        req_id = conn.get("requisition_id", "")
        return html.Div([
            dbc.Alert([
                html.I(className="bi bi-box-arrow-up-right me-2"),
                html.Strong("Bank authentication ready"),
                html.P([
                    "Click the link below to authenticate with your bank via "
                    "GoCardless's secure PSD2 interface. "
                    "After completing authentication, you'll be redirected back here.",
                ], className="mb-2 small"),
                html.A(
                    [html.I(className="bi bi-bank me-1"), "Open bank authentication →"],
                    href=link,
                    target="_blank",
                    className="btn btn-primary btn-sm me-2",
                ),
                dbc.Button(
                    [html.I(className="bi bi-check-circle me-1"), "I've completed authentication"],
                    id="auth-complete-btn",
                    color="success",
                    size="sm",
                    className="mt-2",
                    n_clicks=0,
                ),
            ], color="info", className="mt-2"),
        ]), req_id

    # 4. After user confirms auth, poll requisition and refresh accounts
    @app.callback(
        Output("connected-accounts-body", "children", allow_duplicate=True),
        Input("auth-complete-btn", "n_clicks"),
        [State("bs-active-requisition", "data"),
         State("current-user-store", "data")],
        prevent_initial_call=True,
    )
    def after_auth_complete(n, requisition_id, user_id):
        if not n:
            raise PreventUpdate
        uid = user_id or "_default"

        if requisition_id:
            linked = complete_connection(requisition_id, uid)
            if not linked:
                return dbc.Alert(
                    "Bank connection not yet linked. The bank may still be processing — "
                    "try clicking 'Refresh' in a moment.",
                    color="warning", className="small py-1",
                )

        accounts = fetch_accounts(uid)
        if not accounts:
            return dbc.Alert(
                "No accounts found yet. The bank connection may still be processing — "
                "try refreshing in a moment.",
                color="warning", className="small py-1",
            )
        return html.Div([_account_item(a) for a in accounts])

    # 5. Refresh connected accounts
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

        # On page load, also try to complete any pending connections
        connections = get_user_connections(uid)
        for conn in connections:
            if conn.get("status") in ("CR", "GC", "GA", "SA") and conn.get("requisition_id"):
                complete_connection(conn["requisition_id"], uid)

        accounts = fetch_accounts(uid)
        if not accounts:
            return html.P("No accounts connected yet.",
                          className="text-muted small text-center py-3")
        return html.Div([_account_item(a) for a in accounts])

    # 6. Sync transactions
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

        if triggered == "sync-transactions-btn" and sync_clicks:
            accounts = fetch_accounts(uid)
            all_txs = []
            for acct in accounts:
                acct_id = acct.get("account_id", "")
                if acct_id:
                    txs = sync_transactions(acct_id, uid)
                    rules = load_rules(uid)
                    txs = apply_rules(txs, rules)
                    for tx in txs:
                        tx["_account_id"] = acct_id
                    all_txs.extend(txs)

            if not accounts:
                feedback = dbc.Alert("No accounts to sync. Connect a bank first.",
                                     color="warning", className="small py-1 mb-0")
            else:
                feedback = dbc.Alert(
                    f"Synced {len(all_txs)} transactions from {len(accounts)} account(s).",
                    color="success", className="small py-1 mb-0",
                )

        if not all_txs:
            return (
                html.P("No transactions yet. Sync to load.",
                       className="text-muted small text-center py-4"),
                feedback, all_txs,
                [{"label": "All Categories", "value": ""}],
                [{"label": "All Accounts", "value": ""}],
            )

        normalised = [normalize_transaction(tx) for tx in all_txs]
        cats = sorted(set(n["category"] for n in normalised if n["category"]))
        cat_options = [{"label": "All Categories", "value": ""}] + \
                      [{"label": c, "value": c} for c in cats]
        acct_ids = sorted(set(tx.get("_account_id", "") for tx in all_txs
                              if tx.get("_account_id")))
        acct_options = [{"label": "All Accounts", "value": ""}] + \
                       [{"label": a[:12], "value": a} for a in acct_ids]

        filtered = normalised
        if filter_text:
            q = filter_text.lower()
            filtered = [n for n in filtered
                        if q in n["counterparty"].lower()
                        or q in n["description"].lower()
                        or q in n.get("category", "").lower()]
        if cat_filter:
            filtered = [n for n in filtered if n.get("category") == cat_filter]
        if dir_filter == "in":
            filtered = [n for n in filtered if n["amount"] > 0]
        elif dir_filter == "out":
            filtered = [n for n in filtered if n["amount"] < 0]

        if not filtered:
            rows = html.P("No transactions match your filters.",
                          className="text-muted small text-center py-3")
        else:
            rows = html.Div(
                [_transaction_row(n, i) for i, n in enumerate(filtered[:200])],
                style={"maxHeight": "500px", "overflowY": "auto"},
            )
            if len(filtered) > 200:
                rows = html.Div([
                    rows,
                    html.P(f"Showing 200 of {len(filtered)} transactions.",
                           className="text-muted small text-center mt-2"),
                ])

        return rows, feedback, all_txs, cat_options, acct_options

    # 7. AI categorise
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
            return no_update, dbc.Alert(msg, color="danger",
                                        className="small py-1 mb-0"), no_update

        cat_count = uncategorised_count - sum(1 for tx in cached_txs
                                               if not tx.get("_category"))
        normalised = [normalize_transaction(tx) for tx in cached_txs]
        rows = html.Div(
            [_transaction_row(n, i) for i, n in enumerate(normalised[:200])],
            style={"maxHeight": "500px", "overflowY": "auto"},
        )
        return rows, dbc.Alert(
            f"Categorised {cat_count} transactions using AI.",
            color="success", className="small py-1 mb-0",
        ), cached_txs

    # 8. Open/close add-rule modal
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

    # 9. Create a new rule
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
            return no_update, dbc.Alert("Name and pattern are required.",
                                        color="warning", className="small py-1 mb-0")
        uid = user_id or "_default"
        expected_amount = float(amount) if amount else None
        tol = float(tolerance) / 100 if tolerance else 0.1
        freq_days = int(freq) if freq else 30
        add_rule(uid, name, pattern, category or "Other", expected_amount, tol, freq_days)
        rules = load_rules(uid)
        items = [_rule_item(r) for r in rules]
        return (html.Div(items) if items
                else html.P("No rules.", className="text-muted small text-center py-3")), ""

    # 10. Delete a rule
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
        delete_rule(uid, triggered["index"])
        rules = load_rules(uid)
        if not rules:
            return html.P("No rules yet.",
                          className="text-muted small text-center py-3")
        return html.Div([_rule_item(r) for r in rules])

    # 11. Load rules on page visit
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
            return html.P("No rules yet. Create rules to track recurring transactions.",
                          className="text-muted small text-center py-3")
        return html.Div([_rule_item(r) for r in rules])

    # 12. Monitoring panel
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
            return html.P("Create rules and sync transactions to see monitoring.",
                          className="text-muted small text-center py-3")

        months_back = int(months) if months else 6
        summaries = compute_monitoring_summary(txs, rules, months_back)
        if not summaries:
            return html.P("No recurring rules to monitor.",
                          className="text-muted small text-center py-3")

        ok_count = sum(1 for s in summaries if s["status"] == "OK")
        overdue_count = sum(1 for s in summaries if s["status"] == "OVERDUE")
        missing_count = sum(1 for s in summaries if s["status"] == "MISSING")
        total_cumulative = sum(abs(s["cumulative"]) for s in summaries)

        stats = dbc.Row([
            dbc.Col(html.Div([
                html.Div(str(ok_count), className="fs-4 fw-bold text-success"),
                html.Div("On Track", className="text-muted small"),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(str(overdue_count), className="fs-4 fw-bold text-warning"),
                html.Div("Overdue", className="text-muted small"),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(str(missing_count), className="fs-4 fw-bold text-danger"),
                html.Div("Missing", className="text-muted small"),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(f"€{total_cumulative:,.0f}", className="fs-4 fw-bold"),
                html.Div("Cumulative", className="text-muted small"),
            ], className="text-center"), width=3),
        ], className="mb-3 py-2 bg-light rounded")

        return html.Div([stats, html.Div([_monitoring_row(s) for s in summaries])])

    # 13. Load institutions on initial page load (for default country)
    @app.callback(
        Output("bank-institution-select", "options", allow_duplicate=True),
        Input("url", "pathname"),
        State("bank-country-select", "value"),
        prevent_initial_call=True,
    )
    def load_institutions_on_page(pathname, country):
        if pathname != "/banksync":
            raise PreventUpdate
        if not has_credentials() or not country:
            return [{"label": "Bank sync not configured", "value": ""}]
        institutions = list_institutions(country)
        if not institutions:
            return [{"label": "No banks found", "value": ""}]
        return [{"label": inst["name"], "value": inst["id"]}
                for inst in sorted(institutions, key=lambda i: i["name"])]
