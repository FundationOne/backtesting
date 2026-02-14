"""
Bank Account Sync Page
Connect bank accounts via GoCardless Bank Account Data (PSD2 Open Banking),
sync transactions, categorise with AI, create recurring-transaction rules,
and monitor expected vs actual cash flows.

SECURITY: All user data (connections, transactions, rules) is stored
exclusively in the user's browser (localStorage) and NEVER on the server.
Data is namespaced per user so different users on the same browser
cannot access each other's data.
"""

import dash
from dash import html, dcc, Input, Output, State, ctx, no_update, ALL
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import json
import hashlib
import time
from datetime import datetime, timedelta

from components.bank_api import (
    has_credentials,
    list_institutions,
    create_connection,
    complete_connection,
    fetch_accounts,
    sync_transactions,
    normalize_transaction,
    categorise_transactions_batch,
    load_default_categories,
    make_rule,
    apply_rules,
    compute_monitoring_summary,
    delete_connection_remote,
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


def _bank_connections_modal():
    """Modal with connect-bank and connected-accounts sections."""
    return dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle([
                html.I(className="bi bi-bank me-2"),
                "Manage Bank Connections",
            ]),
            close_button=True,
        ),
        dbc.ModalBody([
            _bank_connect_card(),
            _connected_accounts_card(),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                "Close",
                id="close-bank-connections-modal-btn",
                color="secondary",
                size="sm",
                n_clicks=0,
            ),
        ]),
    ], id="bank-connections-modal", is_open=False, centered=True, size="xl")


def _openai_warning():
    """Inline warning about missing OpenAI API key — shown near the top."""
    return html.Div(id="openai-key-warning", children=[
        dbc.Alert([
            html.I(className="bi bi-exclamation-triangle me-2"),
            html.Strong("AI categorisation requires an OpenAI API key. "),
            "Go to Settings (bottom-left ⚙) to add your key.",
        ], color="warning", className="py-2 px-3 small mb-3",
           dismissable=True, is_open=True),
    ], style={"display": "none"})  # toggled by callback


def _rules_card():
    """Recurring transaction rules management — redesigned."""
    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-arrow-repeat me-2 text-primary"),
                html.Span("Recurring Rules", className="fw-semibold"),
            ], className="d-flex align-items-center"),
            dbc.Button(
                [html.I(className="bi bi-plus-lg me-1"), "New Rule"],
                id="open-add-rule-modal-btn",
                color="primary",
                size="sm",
                className="ms-auto",
                n_clicks=0,
            ),
        ], className="card-header-modern"),
        dbc.CardBody([
            html.P([
                html.I(className="bi bi-info-circle me-1 text-info"),
                "Rules automatically tag transactions matching a counterparty "
                "pattern (e.g. 'netflix') with a category and track whether they "
                "arrive on schedule.",
            ], className="text-muted small mb-2",
               style={"lineHeight": "1.4"}),
            html.Div(id="rules-container", children=[
                html.P("No rules yet — click '+New Rule' to create one.",
                       className="text-muted small text-center py-2 mb-0"),
            ]),
        ], className="p-3"),
    ], className="card-modern mb-3")


def _monitoring_card():
    """Monitoring panel: expected vs actual transactions — redesigned."""
    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-activity me-2 text-success"),
                html.Span("Payment Monitor", className="fw-semibold"),
            ], className="d-flex align-items-center"),
            dbc.Select(
                id="monitoring-months-select",
                options=[
                    {"label": "3 months", "value": "3"},
                    {"label": "6 months", "value": "6"},
                    {"label": "12 months", "value": "12"},
                ],
                value="6",
                size="sm",
                style={"width": "120px"},
                className="ms-auto",
            ),
        ], className="card-header-modern"),
        dbc.CardBody([
            html.P([
                html.I(className="bi bi-info-circle me-1 text-info"),
                "Compares your rules against actual transactions to spot "
                "missed or overdue recurring payments.",
            ], className="text-muted small mb-2",
               style={"lineHeight": "1.4"}),
            html.Div(id="monitoring-container", children=[
                html.P("Add rules and sync transactions to see monitoring.",
                       className="text-muted small text-center py-2 mb-0"),
            ]),
        ], className="p-3"),
    ], className="card-modern mb-3")


def _transactions_card():
    """Transaction list with filters, date-range, and category donut."""
    three_months_ago = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")

    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-receipt me-2"),
                html.Span("Transactions", className="fw-semibold"),
            ], className="d-flex align-items-center"),
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
            # ── Filter row ──
            dbc.Row([
                dbc.Col([
                    dbc.InputGroup([
                        dbc.InputGroupText(
                            html.I(className="bi bi-search"),
                            className="bg-transparent",
                        ),
                        dbc.Input(
                            id="tx-filter-input",
                            placeholder="Search…",
                            size="sm",
                        ),
                    ], size="sm"),
                ], md=3, className="mb-2 mb-md-0"),
                dbc.Col([
                    dbc.Select(
                        id="tx-category-filter",
                        options=[{"label": "All Categories", "value": ""}],
                        value="",
                        size="sm",
                    ),
                ], md=2, className="mb-2 mb-md-0"),
                dbc.Col([
                    dbc.Select(
                        id="tx-account-filter",
                        options=[{"label": "All Accounts", "value": ""}],
                        value="",
                        size="sm",
                    ),
                ], md=2, className="mb-2 mb-md-0"),
                dbc.Col([
                    dbc.Select(
                        id="tx-direction-filter",
                        options=[
                            {"label": "In & Out", "value": ""},
                            {"label": "Income ↑", "value": "in"},
                            {"label": "Expense ↓", "value": "out"},
                        ],
                        value="",
                        size="sm",
                    ),
                ], md=2, className="mb-2 mb-md-0"),
                dbc.Col([
                    dcc.DatePickerRange(
                        id="tx-date-range",
                        start_date=three_months_ago,
                        end_date=today,
                        display_format="DD.MM.YY",
                        style={"fontSize": "0.8rem"},
                        className="dash-date-range-sm",
                    ),
                ], md=3, className="mb-2 mb-md-0"),
            ], className="mb-3 gx-2"),

            html.Div(id="tx-sync-feedback", className="mb-2"),

            # ── Content: table + donut side by side ──
            dbc.Row([
                dbc.Col([
                    html.Div(id="transactions-container", children=[
                        html.P("Connect a bank account and sync to see transactions.",
                               className="text-muted small text-center py-4"),
                    ]),
                ], lg=8),
                dbc.Col([
                    dcc.Graph(
                        id="tx-category-donut",
                        config={"displayModeBar": False},
                        style={"height": "320px"},
                    ),
                ], lg=4, className="d-none d-lg-block"),
            ]),
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
            html.P([
                "A rule automatically matches transactions by counterparty name "
                "and assigns a category. It also tracks their frequency so the "
                "Payment Monitor can alert you when a payment is missing.",
            ], className="text-muted small mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Rule Name", className="small fw-semibold"),
                    dbc.Input(id="rule-name-input",
                              placeholder="e.g. Netflix Subscription", size="sm"),
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
                    dbc.Input(id="rule-pattern-input",
                              placeholder="e.g. netflix, spotify...", size="sm"),
                    html.Small(
                        "Matched case-insensitively against counterparty name "
                        "and transaction description.",
                        className="text-muted",
                    ),
                ], md=12),
            ], className="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Expected Amount (€)", className="small fw-semibold"),
                    dbc.Input(id="rule-amount-input", type="number",
                              placeholder="e.g. 12.99", size="sm", step="0.01"),
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
            dbc.Button("Cancel", id="cancel-rule-btn", color="secondary",
                       size="sm", n_clicks=0),
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
    # ── Client-side data stores (memory only — persisted via JS) ──
    dcc.Store(id="bs-connections-store", storage_type="memory"),
    dcc.Store(id="bs-rules-store", storage_type="memory"),
    dcc.Store(id="bs-transactions-cache", storage_type="memory"),
    dcc.Store(id="bs-active-requisition", storage_type="session"),
    # hidden helper elements
    html.Div(id="bs-save-trigger", style={"display": "none"}),

    # Auth gate — shown when the user is not logged in
    html.Div([
        html.Div([
            html.I(className="bi bi-lock-fill",
                   style={"fontSize": "4rem", "color": "#6c757d"}),
            html.H4("Please log in to access Bank Sync",
                     className="mt-3 text-muted"),
        ], className="text-center", style={"marginTop": "20vh"})
    ], id="bs-auth-gate", style={"display": "none"}),

    # Actual page content — hidden until auth passes
    html.Div(id="bs-page-content", children=[
        # ── Page header with Manage Connections button + badge ──
        html.Div([
            html.Div([
                html.H4([
                    html.I(className="bi bi-bank me-2"),
                    "Bank Account Sync",
                ], className="page-title mb-0"),
                html.P("Connect your bank, categorise transactions, "
                       "track recurring payments.",
                       className="page-subtitle mb-0"),
            ]),
            html.Div([
                dbc.Button([
                    html.I(className="bi bi-plug me-1"),
                    "Connections ",
                    dbc.Badge("0", id="connections-badge",
                              color="light", text_color="primary",
                              className="ms-1"),
                ], id="open-bank-connections-modal-btn",
                   color="primary", size="sm", outline=True,
                   n_clicks=0),
            ]),
        ], className="d-flex align-items-start justify-content-between "
                     "flex-wrap gap-2 page-header"),

        html.Div(id="gc-setup-section", children=[_setup_card()]),

        html.Div(id="gc-main-section", style={"display": "none"}, children=[
            # ── OpenAI warning (near top) ──
            _openai_warning(),

            # ── Rules & Monitoring row (above transactions) ──
            dbc.Row([
                dbc.Col([_rules_card()], lg=5),
                dbc.Col([_monitoring_card()], lg=7),
            ], className="mb-1"),

            # ── Transactions (full width, donut inside) ──
            _transactions_card(),
        ]),

        _add_rule_modal(),
        _bank_connections_modal(),
    ]),
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
                html.Div(masked_iban, className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ]),
        ], className="d-flex align-items-center"),
        html.Div([
            html.Span(bal_str, className="fw-semibold small me-2"),
            dbc.Badge(status, color=status_color, className="small"),
        ], className="d-flex align-items-center"),
    ], className="d-flex align-items-center justify-content-between "
                 "py-2 px-3 border-bottom")


def _transaction_row(tx_norm, idx):
    amount = tx_norm["amount"]
    is_income = amount > 0
    color = "#10b981" if is_income else "#ef4444"
    sign = "+" if is_income else ""
    amount_str = f"{sign}{amount:,.2f} {tx_norm['currency']}"
    cat = tx_norm.get("category", "")
    cat_badge = (
        dbc.Badge(cat, color="light", text_color="dark", className="me-1")
        if cat else ""
    )
    counterparty = tx_norm["counterparty"] or "—"
    desc_short = (
        (tx_norm["description"][:80] + "…")
        if len(tx_norm["description"]) > 80
        else tx_norm["description"]
    )

    return html.Div([
        html.Div([
            html.Div([
                html.Span(tx_norm["date"], className="text-muted me-3",
                          style={"fontSize": "0.75rem", "minWidth": "80px"}),
                html.Div([
                    html.Div(counterparty, className="fw-semibold small"),
                    html.Div(desc_short, className="text-muted",
                             style={"fontSize": "0.7rem"}),
                ]),
            ], className="d-flex align-items-center"),
            html.Div([
                cat_badge,
                html.Span(amount_str, className="fw-semibold small",
                          style={"color": color}),
            ], className="d-flex align-items-center"),
        ], className="d-flex align-items-center justify-content-between"),
    ], className="py-2 px-3 border-bottom tx-row")


def _rule_item(rule):
    freq_map = {
        "7": "Weekly", "14": "Bi-weekly", "30": "Monthly",
        "90": "Quarterly", "365": "Yearly",
    }
    freq_label = freq_map.get(
        str(rule.get("frequency_days", 30)),
        f"Every {rule.get('frequency_days', 30)}d",
    )
    amt_str = (
        f"€{abs(rule.get('expected_amount', 0)):,.2f}"
        if rule.get("expected_amount") else "Any amount"
    )

    return html.Div([
        html.Div([
            html.I(className="bi bi-arrow-repeat me-2 text-primary"),
            html.Div([
                html.Div(rule["name"], className="fw-semibold small"),
                html.Div([
                    dbc.Badge(rule.get("category", ""), color="light",
                              text_color="dark", className="me-1"),
                    html.Span(f"{freq_label} · {amt_str}",
                              className="text-muted",
                              style={"fontSize": "0.7rem"}),
                ], className="d-flex align-items-center mt-1"),
            ]),
        ], className="d-flex align-items-center"),
        dbc.Button(
            html.I(className="bi bi-trash"),
            id={"type": "delete-rule-btn", "index": rule["id"]},
            color="danger", size="sm", outline=True, n_clicks=0,
        ),
    ], className="d-flex align-items-center justify-content-between "
                 "py-2 px-3 border-bottom")


def _monitoring_row(summary):
    status = summary["status"]
    status_colors = {"OK": "success", "OVERDUE": "warning", "MISSING": "danger"}
    status_icon = {
        "OK": "bi-check-circle-fill",
        "OVERDUE": "bi-exclamation-triangle-fill",
        "MISSING": "bi-x-circle-fill",
    }
    status_clr = {"OK": "#10b981", "OVERDUE": "#f59e0b", "MISSING": "#ef4444"}
    expected_total = 0
    if summary["expected_amount"] is not None:
        expected_total = abs(summary["expected_amount"]) * summary["expected_count"]

    return html.Div([
        html.Div([
            html.I(
                className=(
                    f"bi {status_icon.get(status, 'bi-question-circle')} me-2"
                ),
                style={"color": status_clr.get(status, "#6c757d")},
            ),
            html.Div([
                html.Div(summary["name"], className="fw-semibold small"),
                html.Div([
                    dbc.Badge(summary["category"], color="light",
                              text_color="dark", className="me-1"),
                    html.Span(
                        f"Last: {summary['last_date'] or 'Never'}",
                        className="text-muted",
                        style={"fontSize": "0.7rem"},
                    ),
                ], className="d-flex align-items-center mt-1"),
            ]),
        ], className="d-flex align-items-center"),
        html.Div([
            html.Div([
                html.Span(f"{summary['actual_count']}", className="fw-bold"),
                html.Span(f"/{summary['expected_count']}",
                          className="text-muted small"),
            ], className="text-center me-3"),
            html.Div([
                html.Div(f"€{abs(summary['cumulative']):,.2f}",
                         className="small fw-semibold"),
                html.Div(
                    f"exp. €{expected_total:,.2f}" if expected_total else "",
                    className="text-muted",
                    style={"fontSize": "0.7rem"},
                ),
            ], className="text-end me-3"),
            dbc.Badge(status, color=status_colors.get(status, "secondary")),
        ], className="d-flex align-items-center"),
    ], className="d-flex align-items-center justify-content-between "
                 "py-2 px-3 border-bottom")


def _build_donut(normalised):
    """Build a Plotly donut figure from normalised transactions."""
    import plotly.graph_objects as go

    cat_totals = {}
    for n in normalised:
        cat = n.get("category") or "Uncategorised"
        cat_totals[cat] = cat_totals.get(cat, 0) + abs(n["amount"])

    if not cat_totals:
        fig = go.Figure()
        fig.update_layout(
            annotations=[dict(text="No data", x=0.5, y=0.5,
                              font_size=14, showarrow=False)],
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        return fig

    labels = list(cat_totals.keys())
    values = list(cat_totals.values())

    colors = [
        "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
        "#06b6d4", "#ec4899", "#14b8a6", "#f97316", "#84cc16",
        "#a855f7", "#0ea5e9", "#e11d48", "#22d3ee", "#eab308",
        "#64748b",
    ]

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.55,
        textinfo="label+percent",
        textposition="outside",
        textfont=dict(size=10),
        marker=dict(colors=colors[:len(labels)]),
        hovertemplate="%{label}<br>€%{value:,.2f}<br>%{percent}<extra></extra>",
    )])
    fig.update_layout(
        margin=dict(l=5, r=5, t=25, b=5),
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=dict(text="By Category", font=dict(size=12),
                   x=0.5, y=0.98),
    )
    return fig


# ── Helpers ─────────────────────────────────────────────────────────────

# Popular German banks shown first in the dropdown
_DE_PRIORITY_KEYWORDS = [
    "sparkasse", "volksbank", "raiffeisen", "commerzbank", "deutsche bank",
    "ing", "dkb", "n26", "comdirect", "postbank", "hypovereinsbank",
    "consorsbank", "targobank", "norisbank", "sparda", "apobank",
    "psd bank", "santander", "revolut", "trade republic",
]


def _sort_institutions(institutions, country):
    """Sort institutions: popular banks first (for DE), then alphabetical."""
    def _sort_key(inst):
        name_lower = inst.get("name", "").lower()
        if (country or "").upper() == "DE":
            for i, kw in enumerate(_DE_PRIORITY_KEYWORDS):
                if kw in name_lower:
                    return (0, i, name_lower)
        return (1, 0, name_lower)
    return sorted(institutions, key=_sort_key)


def _collect_account_ids(connections):
    """Extract all account UUIDs from linked connections."""
    ids = []
    for conn in (connections or []):
        if conn.get("status") == "LN":
            ids.extend(conn.get("accounts", []))
    return ids


# ── Callbacks ───────────────────────────────────────────────────────────

def register_callbacks(app):

    # ─── 0. Auth gate ───────────────────────────────────────────────────
    @app.callback(
        [Output("bs-auth-gate", "style"),
         Output("bs-page-content", "style")],
        [Input("url", "pathname"),
         Input("current-user-store", "data")],
    )
    def check_bank_sync_auth(pathname, current_user):
        if pathname != "/banksync":
            raise PreventUpdate
        if current_user:
            return {"display": "none"}, {"display": "block"}
        return {"display": "block"}, {"display": "none"}

    # ─── 0b. Load bank data from localStorage on login / page visit ────
    app.clientside_callback(
        """
        function(user, pathname) {
            if (!user || pathname !== "/banksync") {
                return [[], [], []];
            }
            try {
                var pfx = "apex_bank_" + user + "_";
                var conns = JSON.parse(localStorage.getItem(pfx + "conns") || "[]");
                var rules = JSON.parse(localStorage.getItem(pfx + "rules") || "[]");
                var txs   = JSON.parse(localStorage.getItem(pfx + "txns")  || "[]");
                return [conns, rules, txs];
            } catch(e) {
                console.error("Bank data load error:", e);
                return [[], [], []];
            }
        }
        """,
        [Output("bs-connections-store", "data"),
         Output("bs-rules-store", "data"),
         Output("bs-transactions-cache", "data")],
        [Input("current-user-store", "data"),
         Input("url", "pathname")],
    )

    # ─── 0c. Persist bank data to localStorage on every change ─────────
    app.clientside_callback(
        """
        function(connections, rules, transactions, user) {
            if (!user) return "";
            try {
                var pfx = "apex_bank_" + user + "_";
                localStorage.setItem(pfx + "conns", JSON.stringify(connections || []));
                localStorage.setItem(pfx + "rules", JSON.stringify(rules || []));
                localStorage.setItem(pfx + "txns",  JSON.stringify(transactions || []));
            } catch(e) {
                console.error("Bank data save error:", e);
            }
            return "";
        }
        """,
        Output("bs-save-trigger", "children"),
        [Input("bs-connections-store", "data"),
         Input("bs-rules-store", "data"),
         Input("bs-transactions-cache", "data")],
        State("current-user-store", "data"),
    )

    # ─── 0d. Show/hide setup vs main section ───────────────────────────
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

    # ─── 0e. Show/hide OpenAI warning ──────────────────────────────────
    @app.callback(
        Output("openai-key-warning", "style"),
        [Input("url", "pathname"),
         Input("api_key_store", "data")],
    )
    def toggle_openai_warning(pathname, api_key_data):
        if pathname != "/banksync":
            raise PreventUpdate
        api_key = (api_key_data or {}).get("api_key", "")
        if api_key:
            return {"display": "none"}
        return {"display": "block"}

    # ─── 0f. Connection badge count ────────────────────────────────────
    @app.callback(
        Output("connections-badge", "children"),
        Input("bs-connections-store", "data"),
    )
    def update_connection_badge(connections):
        linked = [c for c in (connections or [])
                  if c.get("status") == "LN"]
        return str(len(linked))

    # ─── 1. Load institutions when country changes ─────────────────────
    @app.callback(
        Output("bank-institution-select", "options"),
        Input("bank-country-select", "value"),
    )
    def load_institutions_for_country(country):
        if not country or not has_credentials():
            return [{"label": "Bank sync not configured", "value": ""}]
        institutions = list_institutions(country)
        if not institutions:
            return [{"label": "No banks found for this country", "value": ""}]
        sorted_insts = _sort_institutions(institutions, country)
        return [{"label": i["name"], "value": i["id"]} for i in sorted_insts]

    # ─── 2. Open/close bank-connections modal ──────────────────────────
    @app.callback(
        Output("bank-connections-modal", "is_open"),
        [Input("open-bank-connections-modal-btn", "n_clicks"),
         Input("close-bank-connections-modal-btn", "n_clicks")],
        State("bank-connections-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_bank_connections_modal(open_n, close_n, is_open):
        triggered = ctx.triggered_id
        if triggered == "open-bank-connections-modal-btn":
            return True
        if triggered == "close-bank-connections-modal-btn":
            return False
        return is_open

    # ─── 3. Connect bank → create connection, auto-sync ───────────────
    @app.callback(
        [Output("bank-connect-feedback", "children"),
         Output("bs-active-requisition", "data"),
         Output("bs-connections-store", "data", allow_duplicate=True)],
        Input("connect-bank-btn", "n_clicks"),
        [State("bank-country-select", "value"),
         State("bank-institution-select", "value"),
         State("bs-connections-store", "data")],
        prevent_initial_call=True,
    )
    def start_bank_connection(n, country, institution_id, connections):
        if not n:
            raise PreventUpdate
        if not has_credentials():
            return (
                dbc.Alert("Set up GoCardless credentials first.",
                          color="warning", className="small py-1"),
                no_update, no_update,
            )
        if not institution_id:
            return (
                dbc.Alert("Please select a bank first.",
                          color="warning", className="small py-1"),
                no_update, no_update,
            )

        conn = create_connection(market=country or "DE",
                                 institution_id=institution_id)
        if not conn:
            return (
                dbc.Alert("Failed to create bank connection. Check credentials.",
                          color="danger", className="small py-1"),
                no_update, no_update,
            )

        # Append to connections store (client-side)
        connections = list(connections or [])
        connections.append(conn)

        link = conn.get("link", "")
        req_id = conn.get("requisition_id", "")

        feedback = html.Div([
            dbc.Alert([
                html.I(className="bi bi-box-arrow-up-right me-2"),
                html.Strong("Bank authentication ready"),
                html.P([
                    "Click the link below to authenticate with your bank "
                    "via GoCardless's secure PSD2 interface. "
                    "After completing authentication, click "
                    "'I've completed authentication'.",
                ], className="mb-2 small"),
                html.A(
                    [html.I(className="bi bi-bank me-1"),
                     "Open bank authentication →"],
                    href=link, target="_blank",
                    className="btn btn-primary btn-sm me-2",
                ),
                dbc.Button(
                    [html.I(className="bi bi-check-circle me-1"),
                     "I've completed authentication"],
                    id="auth-complete-btn",
                    color="success", size="sm",
                    className="mt-2", n_clicks=0,
                ),
            ], color="info", className="mt-2"),
        ])
        return feedback, req_id, connections

    # ─── 4. After auth complete → update connection, auto-sync ─────────
    @app.callback(
        [Output("connected-accounts-body", "children", allow_duplicate=True),
         Output("bs-connections-store", "data", allow_duplicate=True),
         Output("bs-transactions-cache", "data", allow_duplicate=True),
         Output("tx-sync-feedback", "children", allow_duplicate=True)],
        Input("auth-complete-btn", "n_clicks"),
        [State("bs-active-requisition", "data"),
         State("bs-connections-store", "data"),
         State("bs-transactions-cache", "data")],
        prevent_initial_call=True,
    )
    def after_auth_complete(n, requisition_id, connections, cached_txs):
        if not n:
            raise PreventUpdate

        connections = list(connections or [])
        cached_txs = list(cached_txs or [])

        if not requisition_id:
            return no_update, no_update, no_update, no_update

        # Poll requisition status
        result = complete_connection(requisition_id)
        if not result or result["status"] != "LN":
            return (
                dbc.Alert(
                    "Bank connection not yet linked. The bank may still be "
                    "processing — try clicking 'Refresh' in a moment.",
                    color="warning", className="small py-1",
                ),
                no_update, no_update, no_update,
            )

        # Update connection in store
        new_accounts = result.get("accounts", [])
        for conn in connections:
            if conn.get("requisition_id") == requisition_id:
                conn["status"] = result["status"]
                conn["accounts"] = new_accounts
                break

        # Fetch account details
        account_ids = _collect_account_ids(connections)
        accounts = fetch_accounts(account_ids)

        if not accounts:
            return (
                dbc.Alert(
                    "No accounts found yet — try refreshing in a moment.",
                    color="warning", className="small py-1",
                ),
                connections, no_update, no_update,
            )

        # Auto-sync transactions for new accounts
        sync_feedback = no_update
        if new_accounts:
            for aid in new_accounts:
                # Get existing txs for this account from cache
                existing = [t for t in cached_txs
                            if t.get("_account_id") == aid]
                new_txs = sync_transactions(aid, existing)
                for tx in new_txs:
                    tx["_account_id"] = aid
                # Remove old txs for this account and add new
                cached_txs = [t for t in cached_txs
                              if t.get("_account_id") != aid]
                cached_txs.extend(new_txs)

            sync_feedback = dbc.Alert(
                f"Auto-synced {len(new_accounts)} new account(s). "
                f"Total: {len(cached_txs)} transactions.",
                color="success", className="small py-1 mb-0",
            )

        accounts_ui = html.Div([_account_item(a) for a in accounts])
        return accounts_ui, connections, cached_txs, sync_feedback

    # ─── 5. Refresh connected accounts ─────────────────────────────────
    @app.callback(
        Output("connected-accounts-body", "children"),
        [Input("refresh-accounts-btn", "n_clicks"),
         Input("url", "pathname"),
         Input("bank-connections-modal", "is_open")],
        [State("bs-connections-store", "data")],
    )
    def refresh_accounts(n, pathname, modal_open, connections):
        if pathname != "/banksync":
            raise PreventUpdate
        if modal_open is False and ctx.triggered_id == "bank-connections-modal":
            raise PreventUpdate

        account_ids = _collect_account_ids(connections)
        if not account_ids:
            return html.P(
                "No accounts connected yet.",
                className="text-muted small text-center py-3",
            )

        accounts = fetch_accounts(account_ids)
        if not accounts:
            return html.P(
                "No accounts connected yet.",
                className="text-muted small text-center py-3",
            )
        return html.Div([_account_item(a) for a in accounts])

    # ─── 6. Sync & filter transactions + donut ─────────────────────────
    @app.callback(
        [Output("transactions-container", "children"),
         Output("tx-sync-feedback", "children"),
         Output("bs-transactions-cache", "data", allow_duplicate=True),
         Output("tx-category-filter", "options"),
         Output("tx-account-filter", "options"),
         Output("tx-category-donut", "figure")],
        [Input("sync-transactions-btn", "n_clicks"),
         Input("tx-filter-input", "value"),
         Input("tx-category-filter", "value"),
         Input("tx-account-filter", "value"),
         Input("tx-direction-filter", "value"),
         Input("tx-date-range", "start_date"),
         Input("tx-date-range", "end_date"),
         Input("bs-transactions-cache", "data")],
        [State("bs-connections-store", "data"),
         State("bs-rules-store", "data"),
         State("api_key_store", "data")],
        prevent_initial_call=True,
    )
    def sync_and_filter_transactions(
        sync_clicks, filter_text, cat_filter, acct_filter, dir_filter,
        date_from, date_to, cached_txs,
        connections, rules, api_key_data,
    ):
        triggered = ctx.triggered_id
        all_txs = list(cached_txs or [])
        feedback = no_update
        store_update = no_update

        # ── Sync button pressed ──
        if triggered == "sync-transactions-btn" and sync_clicks:
            account_ids = _collect_account_ids(connections)
            if not account_ids:
                feedback = dbc.Alert(
                    "No accounts to sync. Connect a bank first.",
                    color="warning", className="small py-1 mb-0",
                )
            else:
                new_all = []
                for aid in account_ids:
                    existing = [t for t in all_txs
                                if t.get("_account_id") == aid]
                    merged = sync_transactions(aid, existing)
                    for tx in merged:
                        tx["_account_id"] = aid
                    new_all.extend(merged)

                # Apply rules
                rules_list = rules or []
                new_all = apply_rules(new_all, rules_list)
                all_txs = new_all
                store_update = all_txs

                feedback = dbc.Alert(
                    f"Synced {len(all_txs)} transactions from "
                    f"{len(account_ids)} account(s).",
                    color="success", className="small py-1 mb-0",
                )

        # ── Empty state ──
        if not all_txs:
            import plotly.graph_objects as go
            empty_fig = go.Figure()
            empty_fig.update_layout(
                annotations=[dict(text="No data", x=0.5, y=0.5,
                                  font_size=14, showarrow=False)],
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            return (
                html.P("No transactions yet. Sync to load.",
                       className="text-muted small text-center py-4"),
                feedback, store_update,
                [{"label": "All Categories", "value": ""}],
                [{"label": "All Accounts", "value": ""}],
                empty_fig,
            )

        # ── Normalise ──
        normalised = [normalize_transaction(tx) for tx in all_txs]

        # ── Build filter dropdowns ──
        cats = sorted(set(n["category"] for n in normalised if n["category"]))
        cat_options = ([{"label": "All Categories", "value": ""}]
                       + [{"label": c, "value": c} for c in cats])
        acct_ids = sorted(set(
            tx.get("_account_id", "") for tx in all_txs if tx.get("_account_id")
        ))
        acct_options = ([{"label": "All Accounts", "value": ""}]
                        + [{"label": a[:12], "value": a} for a in acct_ids])

        # ── Apply filters ──
        filtered = normalised

        if date_from:
            filtered = [n for n in filtered if n["date"] >= date_from]
        if date_to:
            filtered = [n for n in filtered if n["date"] <= date_to]
        if filter_text:
            q = filter_text.lower()
            filtered = [n for n in filtered
                        if q in n["counterparty"].lower()
                        or q in n["description"].lower()
                        or q in n.get("category", "").lower()]
        if cat_filter:
            filtered = [n for n in filtered
                        if n.get("category") == cat_filter]
        if acct_filter:
            # Need to match back to raw txs
            matching_ids = set()
            for tx in all_txs:
                if tx.get("_account_id") == acct_filter:
                    norm = normalize_transaction(tx)
                    matching_ids.add(norm["id"])
            filtered = [n for n in filtered if n["id"] in matching_ids]
        if dir_filter == "in":
            filtered = [n for n in filtered if n["amount"] > 0]
        elif dir_filter == "out":
            filtered = [n for n in filtered if n["amount"] < 0]

        # ── Donut chart ──
        donut_fig = _build_donut(filtered)

        # ── Rows ──
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

        return rows, feedback, store_update, cat_options, acct_options, donut_fig

    # ─── 7. AI categorise ──────────────────────────────────────────────
    @app.callback(
        [Output("transactions-container", "children", allow_duplicate=True),
         Output("tx-sync-feedback", "children", allow_duplicate=True),
         Output("bs-transactions-cache", "data", allow_duplicate=True)],
        Input("ai-categorise-btn", "n_clicks"),
        [State("bs-transactions-cache", "data"),
         State("api_key_store", "data")],
        prevent_initial_call=True,
    )
    def ai_categorise(n, cached_txs, api_key_data):
        if not n or not cached_txs:
            raise PreventUpdate

        api_key = (api_key_data or {}).get("api_key", "")
        if not api_key:
            return (
                no_update,
                dbc.Alert([
                    html.I(className="bi bi-exclamation-triangle me-1"),
                    "Set your OpenAI API key in Settings first.",
                ], color="warning", className="small py-1 mb-0"),
                no_update,
            )

        uncategorised_count = sum(
            1 for tx in cached_txs if not tx.get("_category")
        )
        if uncategorised_count == 0:
            return (
                no_update,
                dbc.Alert("All transactions are already categorised!",
                          color="info", className="small py-1 mb-0"),
                no_update,
            )

        try:
            cached_txs = categorise_transactions_batch(cached_txs, api_key)
        except Exception as e:
            err_str = str(e)
            if "invalid_api_key" in err_str or "401" in err_str:
                msg = "Invalid OpenAI API key. Check your key in Settings."
            else:
                msg = f"Categorisation error: {err_str[:100]}"
            return (
                no_update,
                dbc.Alert(msg, color="danger", className="small py-1 mb-0"),
                no_update,
            )

        cat_count = uncategorised_count - sum(
            1 for tx in cached_txs if not tx.get("_category")
        )
        normalised = [normalize_transaction(tx) for tx in cached_txs]
        rows = html.Div(
            [_transaction_row(n, i) for i, n in enumerate(normalised[:200])],
            style={"maxHeight": "500px", "overflowY": "auto"},
        )
        return (
            rows,
            dbc.Alert(f"Categorised {cat_count} transactions using AI.",
                      color="success", className="small py-1 mb-0"),
            cached_txs,
        )

    # ─── 8. Open/close add-rule modal ──────────────────────────────────
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

    # ─── 9. Create a new rule (stored in browser) ─────────────────────
    @app.callback(
        [Output("rules-container", "children", allow_duplicate=True),
         Output("add-rule-feedback", "children"),
         Output("bs-rules-store", "data", allow_duplicate=True)],
        Input("confirm-add-rule-btn", "n_clicks"),
        [State("rule-name-input", "value"),
         State("rule-category-select", "value"),
         State("rule-pattern-input", "value"),
         State("rule-amount-input", "value"),
         State("rule-tolerance-input", "value"),
         State("rule-frequency-select", "value"),
         State("bs-rules-store", "data")],
        prevent_initial_call=True,
    )
    def create_rule_cb(n, name, category, pattern, amount, tolerance,
                       freq, rules):
        if not n:
            raise PreventUpdate
        if not name or not pattern:
            return (
                no_update,
                dbc.Alert("Name and pattern are required.",
                          color="warning", className="small py-1 mb-0"),
                no_update,
            )

        expected_amount = float(amount) if amount else None
        tol = float(tolerance) / 100 if tolerance else 0.1
        freq_days = int(freq) if freq else 30

        rule = make_rule(name, pattern, category or "Other",
                         expected_amount, tol, freq_days)

        rules = list(rules or [])
        rules.append(rule)

        items = [_rule_item(r) for r in rules]
        ui = (html.Div(items) if items
              else html.P("No rules.", className="text-muted small "
                          "text-center py-3"))
        return ui, "", rules

    # ─── 10. Delete a rule (from browser store) ───────────────────────
    @app.callback(
        [Output("rules-container", "children"),
         Output("bs-rules-store", "data", allow_duplicate=True)],
        Input({"type": "delete-rule-btn", "index": ALL}, "n_clicks"),
        State("bs-rules-store", "data"),
        prevent_initial_call=True,
    )
    def remove_rule(n_clicks_list, rules):
        if not any(n_clicks_list):
            raise PreventUpdate
        triggered = ctx.triggered_id
        if not triggered or not isinstance(triggered, dict):
            raise PreventUpdate

        rule_id = triggered["index"]
        rules = [r for r in (rules or []) if r["id"] != rule_id]

        if not rules:
            return (
                html.P("No rules yet — click '+New Rule' to create one.",
                       className="text-muted small text-center py-2 mb-0"),
                rules,
            )
        return html.Div([_rule_item(r) for r in rules]), rules

    # ─── 11. Load rules on page visit ─────────────────────────────────
    @app.callback(
        Output("rules-container", "children", allow_duplicate=True),
        Input("bs-rules-store", "data"),
        prevent_initial_call=True,
    )
    def render_rules(rules):
        rules = rules or []
        if not rules:
            return html.P(
                "No rules yet — click '+New Rule' to create one.",
                className="text-muted small text-center py-2 mb-0",
            )
        return html.Div([_rule_item(r) for r in rules])

    # ─── 12. Monitoring panel ─────────────────────────────────────────
    @app.callback(
        Output("monitoring-container", "children"),
        [Input("monitoring-months-select", "value"),
         Input("bs-rules-store", "data"),
         Input("bs-transactions-cache", "data")],
    )
    def update_monitoring(months, rules, cached_txs):
        rules = rules or []
        txs = cached_txs or []

        if not rules or not txs:
            return html.P(
                "Add rules and sync transactions to see monitoring.",
                className="text-muted small text-center py-2 mb-0",
            )

        months_back = int(months) if months else 6
        summaries = compute_monitoring_summary(txs, rules, months_back)
        if not summaries:
            return html.P(
                "No recurring rules to monitor.",
                className="text-muted small text-center py-2 mb-0",
            )

        ok_count = sum(1 for s in summaries if s["status"] == "OK")
        overdue_count = sum(1 for s in summaries if s["status"] == "OVERDUE")
        missing_count = sum(1 for s in summaries if s["status"] == "MISSING")
        total_cumulative = sum(abs(s["cumulative"]) for s in summaries)

        stats = dbc.Row([
            dbc.Col(html.Div([
                html.Div(str(ok_count),
                         className="fs-5 fw-bold text-success"),
                html.Div("On Track", className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(str(overdue_count),
                         className="fs-5 fw-bold text-warning"),
                html.Div("Overdue", className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(str(missing_count),
                         className="fs-5 fw-bold text-danger"),
                html.Div("Missing", className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(f"€{total_cumulative:,.0f}",
                         className="fs-5 fw-bold"),
                html.Div("Cumulative", className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ], className="text-center"), width=3),
        ], className="mb-2 py-2 bg-light rounded")

        return html.Div([
            stats,
            html.Div([_monitoring_row(s) for s in summaries]),
        ])
