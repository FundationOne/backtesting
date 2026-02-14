"""
Bank Account Sync Page
Connect bank accounts via GoCardless Bank Account Data (PSD2 Open Banking),
sync transactions, categorise with AI, create recurring-transaction rules,
and monitor expected vs actual cash flows.

SECURITY: Persisted data (connections + transactions) is stored
exclusively in the user's browser (localStorage) and NEVER on the server.
Rules are kept in memory for the active session unless you extend persistence.
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
from components.i18n import t, get_lang
from components.multi_select import multi_filter, register_multi_select_callbacks

# ── Layout ──────────────────────────────────────────────────────────────

def _setup_card(lang="en"):
    """Shown when GoCardless credentials are not configured server-side."""
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.I(className="bi bi-exclamation-triangle",
                       style={"fontSize": "2.5rem", "color": "#f59e0b"}),
            ], className="text-center mb-3"),
            html.H5(t("bs.not_available", lang), className="text-center mb-2"),
            html.P(
                t("bs.not_configured", lang),
                className="text-center text-muted small mb-0",
            ),
        ])
    ], className="card-modern mb-4", style={"maxWidth": "520px", "margin": "0 auto"})


def _bank_connect_card(lang="en"):
    """Bank connection via GoCardless requisition flow."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-link-45deg me-2"),
            t("bs.connect_bank", lang),
        ], className="card-header-modern"),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label(t("bs.country", lang), className="small fw-semibold"),
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
                    dbc.Label(t("bs.bank", lang), className="small fw-semibold"),
                    dbc.Select(
                        id="bank-institution-select",
                        options=[{"label": t("bs.select_country_first", lang), "value": ""}],
                        value="",
                        size="sm",
                    ),
                ], md=5),
                dbc.Col([
                    dbc.Label(" ", className="small"),
                    dbc.Button(
                        [html.I(className="bi bi-bank me-2"), t("bs.connect_btn", lang)],
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
                    t("bs.connect_info", lang),
                ], className="text-muted small mb-0"),
            ]),
        ]),
    ], className="card-modern mb-4")


def _connected_accounts_card(lang="en"):
    """Shows connected bank accounts with balances."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-wallet2 me-2"),
            t("bs.connected_accounts", lang),
            dbc.Button(
                [html.I(className="bi bi-arrow-clockwise me-1"), t("bs.refresh", lang)],
                id="refresh-accounts-btn",
                color="link",
                size="sm",
                className="ms-auto p-0",
                n_clicks=0,
            ),
        ], className="card-header-modern"),
        dbc.CardBody(id="connected-accounts-body", children=[
            html.P(t("bs.no_accounts", lang), className="text-muted small text-center py-3"),
        ]),
    ], className="card-modern mb-4")


def _bank_connections_modal(lang="en"):
    """Modal with connect-bank and connected-accounts sections."""
    return dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle([
                html.I(className="bi bi-bank me-2"),
                t("bs.manage_connections", lang),
            ]),
            close_button=True,
        ),
        dbc.ModalBody([
            _bank_connect_card(lang),
            _connected_accounts_card(lang),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                t("bs.close", lang),
                id="close-bank-connections-modal-btn",
                color="secondary",
                size="sm",
                n_clicks=0,
            ),
        ]),
    ], id="bank-connections-modal", is_open=False, centered=True, size="xl")


def _openai_warning(lang="en"):
    """Inline warning about missing OpenAI API key — shown near the top."""
    return html.Div(id="openai-key-warning", children=[
        dbc.Alert([
            html.I(className="bi bi-exclamation-triangle me-2"),
            html.Strong(t("bs.openai_warning", lang)),
            html.A(
                t("bs.open_settings", lang),
                id="open-settings-link-warning",
                href="#",
                className="alert-link",
                style={"cursor": "pointer", "textDecoration": "underline"},
            ),
            t("bs.to_add_key", lang),
        ], color="warning", className="py-2 px-3 small mb-3",
           dismissable=True, is_open=True),
    ], style={"display": "none"})  # toggled by callback


def _rules_card(lang="en"):
    """Recurring transaction rules management — redesigned."""
    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-arrow-repeat me-2 text-primary"),
                html.Span(t("bs.recurring_rules", lang), className="fw-semibold"),
            ], className="d-flex align-items-center"),
            dbc.Button(
                [html.I(className="bi bi-plus-lg me-1"), t("bs.new_rule", lang)],
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
                t("bs.rules_help", lang),
            ], className="text-muted small mb-2",
               style={"lineHeight": "1.4"}),
            html.Div(id="rules-container", children=[
                html.P(t("bs.no_rules", lang),
                       className="text-muted small text-center py-2 mb-0"),
            ]),
        ], className="p-3"),
    ], className="card-modern mb-3")


def _monitoring_card(lang="en"):
    """Monitoring panel: expected vs actual transactions — redesigned."""
    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-activity me-2 text-success"),
                html.Span(t("bs.payment_monitor", lang), className="fw-semibold"),
            ], className="d-flex align-items-center"),
            dbc.Select(
                id="monitoring-months-select",
                options=[
                    {"label": t("bs.3_months", lang), "value": "3"},
                    {"label": t("bs.6_months", lang), "value": "6"},
                    {"label": t("bs.12_months", lang), "value": "12"},
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
                t("bs.monitoring_help", lang),
            ], className="text-muted small mb-2",
               style={"lineHeight": "1.4"}),
            html.Div(id="monitoring-container", children=[
                html.P(t("bs.add_rules_first", lang),
                       className="text-muted small text-center py-2 mb-0"),
            ]),
        ], className="p-3"),
    ], className="card-modern mb-3")


def _transactions_card(lang="en"):
    """Transaction list with filters, date-range, and category donut."""
    three_months_ago = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")

    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-receipt me-2"),
                html.Span(t("bs.transactions", lang), className="fw-semibold"),
            ], className="d-flex align-items-center"),
            html.Div([
                dbc.Button(
                    [html.I(className="bi bi-arrow-clockwise me-1"), t("bs.sync", lang)],
                    id="sync-transactions-btn",
                    color="primary",
                    size="sm",
                    outline=True,
                    className="me-2",
                    n_clicks=0,
                ),
                dbc.Button(
                    [html.I(className="bi bi-robot me-1"), t("bs.ai_categorise", lang)],
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
                    multi_filter("tx-category-filter",
                                 t("bs.all_categories", lang)),
                ], md=2, className="mb-2 mb-md-0"),
                dbc.Col([
                    multi_filter("tx-account-filter",
                                 t("bs.all_accounts", lang)),
                ], md=2, className="mb-2 mb-md-0"),
                dbc.Col([
                    multi_filter("tx-direction-filter",
                                  t("bs.in_out", lang),
                                  options=[
                                      {"label": t("bs.income", lang), "value": "in"},
                                      {"label": t("bs.expense", lang), "value": "out"},
                                  ]),
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
                dbc.Col([
                    dbc.InputGroup([
                        dbc.InputGroupText(
                            html.I(className="bi bi-search"),
                            className="bg-transparent",
                        ),
                        dbc.Input(
                            id="tx-filter-input",
                            placeholder=t("bs.search", lang),
                            size="sm",
                            className="bs-filter-control",
                        ),
                    ], size="sm", className="bs-filter-search"),
                ], md=3, className="mb-2 mb-md-0"),
            ], className="mb-3 gx-2 bs-filter-row"),

            html.Div(id="tx-sync-feedback", className="mb-2"),

            dcc.Loading(
                id="tx-loading",
                type="default",
                color="#6366f1",
                children=[
                    # ── Content: table + donut side by side ──
                    dbc.Row([
                        dbc.Col([
                            html.Div(id="transactions-container", children=[
                                html.P(t("bs.connect_first", lang),
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
                ],
            ),
        ]),
    ], className="card-modern mb-4")


def _add_rule_modal(lang="en"):
    """Modal for adding a transaction rule."""
    categories = load_default_categories()
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle([
            html.I(className="bi bi-plus-circle me-2"),
            t("bs.create_rule", lang),
        ]), close_button=True),
        dbc.ModalBody([
            html.P([
                t("bs.rule_help", lang),
            ], className="text-muted small mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label(t("bs.rule_name", lang), className="small fw-semibold"),
                    dbc.Input(id="rule-name-input",
                              placeholder=t("bs.rule_name_ph", lang), size="sm"),
                ], md=6),
                dbc.Col([
                    dbc.Label(t("bs.category", lang), className="small fw-semibold"),
                    multi_filter(
                        "rule-category-select",
                        t("bs.all_categories", lang),
                        options=[{"label": c, "value": c} for c in categories],
                    ),
                ], md=6),
            ], className="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label(t("bs.counterparty_pattern", lang), className="small fw-semibold"),
                    dbc.Input(id="rule-pattern-input",
                              placeholder=t("bs.pattern_ph", lang), size="sm"),
                    html.Small(
                        t("bs.pattern_help", lang),
                        className="text-muted",
                    ),
                ], md=12),
            ], className="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label(t("bs.expected_amount", lang), className="small fw-semibold"),
                    dbc.Input(id="rule-amount-input", type="number",
                              placeholder="e.g. 12.99", size="sm", step="0.01"),
                ], md=4),
                dbc.Col([
                    dbc.Label(t("bs.tolerance", lang), className="small fw-semibold"),
                    dbc.Input(id="rule-tolerance-input", type="number", value=10,
                              size="sm", min=0, max=100, step=1),
                ], md=4),
                dbc.Col([
                    dbc.Label(t("bs.frequency", lang), className="small fw-semibold"),
                    dbc.Select(
                        id="rule-frequency-select",
                        options=[
                            {"label": t("bs.weekly", lang), "value": "7"},
                            {"label": t("bs.biweekly", lang), "value": "14"},
                            {"label": t("bs.monthly", lang), "value": "30"},
                            {"label": t("bs.quarterly", lang), "value": "90"},
                            {"label": t("bs.yearly", lang), "value": "365"},
                        ],
                        value="30",
                        size="sm",
                    ),
                ], md=4),
            ]),
        ]),
        dbc.ModalFooter([
            html.Div(id="add-rule-feedback", className="me-auto"),
            dbc.Button(t("bs.cancel", lang), id="cancel-rule-btn", color="secondary",
                       size="sm", n_clicks=0),
            dbc.Button(
                [html.I(className="bi bi-check-lg me-1"), t("bs.create_rule_btn", lang)],
                id="confirm-add-rule-btn",
                color="primary",
                size="sm",
                n_clicks=0,
            ),
        ]),
    ], id="add-rule-modal", is_open=False, centered=True, size="lg")


# ── Main layout ────────────────────────────────────────────────────────

def layout(lang="en"):
  return html.Div([
    # ── Stores (memory) — persisted to localStorage via JS callbacks ──
    dcc.Store(id="bs-connections-store", storage_type="memory"),
    dcc.Store(id="bs-rules-store", storage_type="memory"),
    dcc.Store(id="bs-transactions-cache", storage_type="memory"),
    dcc.Store(id="bs-active-requisition", storage_type="session"),
    html.Div(id="bs-save-trigger", style={"display": "none"}),
    html.Div(id="bs-save-result", style={"display": "none"}),
    html.Div(id="bs-ai-log-trigger", style={"display": "none"}),
    # Trigger: fires callback 0b every time this page renders
    html.Div(id="bs-page-ready", children="1", style={"display": "none"}),

    # Auth gate — shown when the user is not logged in
    html.Div([
        html.Div([
            html.I(className="bi bi-lock-fill",
                   style={"fontSize": "4rem", "color": "#6c757d"}),
            html.H4(t("bs.auth_gate", lang),
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
                    t("bs.title", lang),
                ], className="page-title mb-0"),
                html.P(t("bs.subtitle", lang),
                       className="page-subtitle mb-0"),
            ]),
            html.Div([
                dbc.Button([
                    html.I(className="bi bi-plug me-1"),
                    t("bs.connections", lang),
                    dbc.Badge("0", id="connections-badge",
                              color="light", text_color="primary",
                              className="ms-1"),
                ], id="open-bank-connections-modal-btn",
                   color="primary", size="sm", outline=True,
                   n_clicks=0),
            ]),
        ], className="d-flex align-items-start justify-content-between "
                     "flex-wrap gap-2 page-header"),

        html.Div(id="gc-setup-section",
                 style={"display": "none"} if has_credentials() else {},
                 children=[_setup_card(lang)]),

        html.Div(id="gc-main-section",
                 style={} if has_credentials() else {"display": "none"},
                 children=[
            # ── OpenAI warning (near top) ──
            _openai_warning(lang),

            # ── Rules & Monitoring row (above transactions) ──
            dbc.Row([
                dbc.Col([_rules_card(lang)], lg=5),
                dbc.Col([_monitoring_card(lang)], lg=7),
            ], className="mb-1"),

            # ── Transactions (full width, donut inside) ──
            _transactions_card(lang),
        ]),

        _add_rule_modal(lang),
        _bank_connections_modal(lang),
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


def _rule_item(rule, lang="en"):
    freq_map = {
        "7": t("bs.weekly", lang), "14": t("bs.biweekly", lang),
        "30": t("bs.monthly", lang),
        "90": t("bs.quarterly", lang), "365": t("bs.yearly", lang),
    }
    freq_label = freq_map.get(
        str(rule.get("frequency_days", 30)),
        t("bs.every_n_days", lang).format(n=rule.get('frequency_days', 30)),
    )
    amt_str = (
        f"€{abs(rule.get('expected_amount', 0)):,.2f}"
        if rule.get("expected_amount") else t("bs.any_amount", lang)
    )
    match_categories = [c for c in (rule.get("match_categories") or []) if c]
    category_badge = rule.get("category", "")
    if len(match_categories) > 1:
        category_badge = f"{match_categories[0]} +{len(match_categories) - 1}"

    return html.Div([
        html.Div([
            html.I(className="bi bi-arrow-repeat me-2 text-primary"),
            html.Div([
                html.Div(rule["name"], className="fw-semibold small"),
                html.Div([
                    dbc.Badge(category_badge, color="light",
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


def _monitoring_row(summary, lang="en"):
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
                        t("bs.last_date", lang).format(date=summary['last_date'] or t("bs.never", lang)),
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
                    t("bs.exp_amount", lang).format(amount=f"{expected_total:,.2f}") if expected_total else "",
                    className="text-muted",
                    style={"fontSize": "0.7rem"},
                ),
            ], className="text-end me-3"),
            dbc.Badge(status, color=status_colors.get(status, "secondary")),
        ], className="d-flex align-items-center"),
    ], className="d-flex align-items-center justify-content-between "
                 "py-2 px-3 border-bottom")


def _build_donut(normalised, lang="en"):
    """Build a Plotly donut figure from normalised transactions."""
    import plotly.graph_objects as go

    cat_totals = {}
    for n in normalised:
        cat = n.get("category") or "Uncategorised"
        cat_totals[cat] = cat_totals.get(cat, 0) + abs(n["amount"])

    if not cat_totals:
        fig = go.Figure()
        fig.update_layout(
            annotations=[dict(text=t("bs.no_data", lang), x=0.5, y=0.5,
                              font_size=14, showarrow=False)],
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        return fig

    sorted_items = sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)
    total_value = sum(v for _, v in sorted_items) or 1

    max_visible = 7
    min_share = 0.02  # 2%
    compact_items = []
    other_total = 0.0
    for idx, (label, value) in enumerate(sorted_items):
        share = value / total_value
        if idx < max_visible and share >= min_share:
            compact_items.append((label, value))
        else:
            other_total += value

    if other_total > 0:
        compact_items.append(("Other", other_total))

    labels = [k for k, _ in compact_items]
    values = [v for _, v in compact_items]

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
        textinfo="percent",
        textposition="inside",
        textfont=dict(size=10),
        insidetextorientation="horizontal",
        marker=dict(colors=colors[:len(labels)]),
        hovertemplate="%{label}<br>€%{value:,.2f}<br>%{percent}<extra></extra>",
    )])
    fig.update_layout(
        margin=dict(l=5, r=120, t=25, b=5),
        showlegend=True,
        legend=dict(
            orientation="v",
            x=1.02,
            y=0.5,
            yanchor="middle",
            font=dict(size=10),
        ),
        uniformtext_minsize=9,
        uniformtext_mode="hide",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=dict(text=t("bs.by_category", lang), font=dict(size=12),
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


def _tx_date(tx):
    return tx.get("bookingDate") or tx.get("valueDate") or ""


def _tx_identity(tx):
    tx_id = (
        tx.get("transactionId")
        or tx.get("internalTransactionId")
        or tx.get("entryReference")
        or tx.get("_generated_id")
        or ""
    )
    if tx_id:
        return str(tx_id)

    tx_copy = dict(tx)
    tx_copy.pop("_generated_id", None)
    return hashlib.md5(
        json.dumps(tx_copy, sort_keys=True, default=str).encode()
    ).hexdigest()


def _append_only_newer_transactions(existing, merged):
    """Return only truly new (newer) txs from merged without touching existing."""
    existing = list(existing or [])
    merged = list(merged or [])

    existing_ids = {_tx_identity(tx) for tx in existing}
    last_date = max((_tx_date(tx) for tx in existing), default="")

    added = []
    added_ids = set()
    for tx in merged:
        tx_id = _tx_identity(tx)
        tx_date = _tx_date(tx)

        if tx_id in existing_ids or tx_id in added_ids:
            continue
        if last_date and tx_date and tx_date <= last_date:
            continue

        added.append(tx)
        added_ids.add(tx_id)

    return added


# ── Callbacks ───────────────────────────────────────────────────────────

def register_callbacks(app):

    # ─── Multi-select filter callbacks ──────────────────────────────────
    register_multi_select_callbacks(app, [
        ("tx-category-filter", "All categories"),
        ("tx-account-filter", "All accounts"),
        ("tx-direction-filter", "In & Out"),
        ("rule-category-select", "All categories"),
    ])

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

    # ─── 0b. Load persisted bank data on login / page visit ────────────
    # Persisted scope: connections + transactions only.
    app.clientside_callback(
        """
        function(ready, pageStyle, user) {
            if (!user) {
                console.log("[bank-load] skipped: no current user");
                return [window.dash_clientside.no_update,
                        window.dash_clientside.no_update,
                        window.dash_clientside.no_update];
            }
            try {
                var pfx = "apex_bank_" + user + "_";
                console.groupCollapsed("[bank-load] user=" + user);

                function loadFromKeys(keys) {
                    for (var i = 0; i < keys.length; i++) {
                        var raw = localStorage.getItem(pfx + keys[i]);
                        if (!raw) continue;
                        try {
                            var parsed = JSON.parse(raw);
                            if (Array.isArray(parsed) && parsed.length > 0) {
                                return {data: parsed, key: keys[i], rawLen: raw.length};
                            }
                            if (Array.isArray(parsed)) {
                                return {data: parsed, key: keys[i], rawLen: raw.length};
                            }
                        } catch (e) {
                            console.warn("[bank-load] Could not parse key", pfx + keys[i], e);
                        }
                    }
                    return {data: [], key: null, rawLen: 0};
                }

                function isTransactionLike(item) {
                    if (!item || typeof item !== "object") return false;
                    return (
                        item.hasOwnProperty("_account_id") ||
                        item.hasOwnProperty("transactionAmount") ||
                        item.hasOwnProperty("bookingDate") ||
                        item.hasOwnProperty("valueDate") ||
                        item.hasOwnProperty("amount") ||
                        item.hasOwnProperty("_txid")
                    );
                }

                function scanUserPrefixedKeysForTransactions() {
                    var best = {data: [], key: null, rawLen: 0};
                    var keyDump = [];
                    for (var i = 0; i < localStorage.length; i++) {
                        var k = localStorage.key(i);
                        if (!k || k.indexOf(pfx) !== 0) continue;

                        var raw = localStorage.getItem(k);
                        var info = {key: k, bytes: raw ? raw.length : 0, kind: "non-array", count: 0, txLike: false};

                        if (!raw) {
                            keyDump.push(info);
                            continue;
                        }

                        try {
                            var parsed = JSON.parse(raw);
                            if (Array.isArray(parsed)) {
                                info.kind = "array";
                                info.count = parsed.length;
                                info.txLike = parsed.length > 0 && isTransactionLike(parsed[0]);
                                if (info.txLike && parsed.length > best.data.length) {
                                    best = {data: parsed, key: k.replace(pfx, ""), rawLen: raw.length};
                                }
                            }
                        } catch (e) {
                            info.kind = "invalid-json";
                        }

                        keyDump.push(info);
                    }

                    console.table(keyDump);
                    return best;
                }

                var connsRes = loadFromKeys(["conns", "connections"]);
                var txsRes   = loadFromKeys(["txns", "txs", "transactions"]);
                var conns = connsRes.data || [];
                var txs   = txsRes.data || [];

                console.log("prefix:", pfx);
                console.log("connections source key:", connsRes.key || "none", "count:", conns.length, "bytes:", connsRes.rawLen || 0);
                console.log("transactions source key:", txsRes.key || "none", "count:", txs.length, "bytes:", txsRes.rawLen || 0);

                // Recovery fallback: if canonical/known tx keys are empty, scan all
                // user-prefixed keys for transaction-like arrays.
                if (!txs || txs.length === 0) {
                    var fallback = scanUserPrefixedKeysForTransactions();
                    if (fallback.key && fallback.data && fallback.data.length > 0) {
                        txs = fallback.data;
                        txsRes = fallback;
                        console.log("recovered txs from fallback key:", pfx + fallback.key,
                                    "count:", txs.length, "bytes:", fallback.rawLen || 0);
                    } else {
                        console.log("no tx fallback candidate found under prefix", pfx);
                    }
                }

                // Canonicalize key names so next explicit save uses one format.
                if (connsRes.key && connsRes.key !== "conns") {
                    localStorage.setItem(pfx + "conns", JSON.stringify(conns));
                    console.log("migrated key:", pfx + connsRes.key, "->", pfx + "conns");
                }
                if (txsRes.key && txsRes.key !== "txns") {
                    localStorage.setItem(pfx + "txns", JSON.stringify(txs));
                    console.log("migrated key:", pfx + txsRes.key, "->", pfx + "txns");
                }

                console.log("[bank-load] Loaded", conns.length, "conns,", txs.length, "txs for user", user);
                console.groupEnd();
                return [conns, [], txs];
            } catch(e) {
                console.error("Bank data load error:", e);
                try { console.groupEnd(); } catch(_) {}
                // On error, do NOT overwrite stores — keep whatever is there
                return [window.dash_clientside.no_update,
                        window.dash_clientside.no_update,
                        window.dash_clientside.no_update];
            }
        }
        """,
        [Output("bs-connections-store", "data"),
         Output("bs-rules-store", "data"),
         Output("bs-transactions-cache", "data")],
        [Input("bs-page-ready", "children"),
         Input("bs-page-content", "style")],
        State("current-user-store", "data"),
    )

    # ─── 0c. Persist bank data only on explicit user action ────────────
    # Triggered by server callbacks that mutate connections/transactions.
    app.clientside_callback(
        """
        function(saveSignal, connections, transactions, user) {
            if (!saveSignal) {
                console.log("[bank-save] skipped: no explicit save signal");
                return "";
            }
            if (!user) {
                console.log("[bank-save] skipped: no current user; signal=", saveSignal);
                return "";
            }

            var pfx = "apex_bank_" + user + "_";
            console.groupCollapsed("[bank-save] user=" + user + " signal=" + saveSignal);

            var action = String(saveSignal).split(":")[0] || "unknown";
            var allowConnsWrite = (action === "connect" || action === "auth-complete");
            var allowTxWrite = (action === "sync" || action === "ai-categorise" || action === "auth-complete");

            // RULE: never write null or empty arrays over existing data.
            function backupCurrent(key) {
                var existing = localStorage.getItem(pfx + key);
                if (!existing || existing === "[]" || existing === "null") {
                    return false;
                }
                localStorage.setItem(pfx + key + "__bak", existing);
                localStorage.setItem(pfx + key + "__bak_ts", String(Date.now()));
                return true;
            }

            function safeSave(key, data, allowWrite) {
                if (!allowWrite) {
                    return "skipped-action";
                }

                var hasContent = Array.isArray(data) && data.length > 0;
                if (hasContent) {
                    backupCurrent(key);
                    localStorage.setItem(pfx + key, JSON.stringify(data));
                    return "written";
                }
                var existing = localStorage.getItem(pfx + key);
                if (!existing || existing === "[]" || existing === "null") {
                    localStorage.setItem(pfx + key, JSON.stringify(data || []));
                    return "written-empty";
                }
                return "kept-existing";
            }

            try {
                var s1 = safeSave("conns", connections, allowConnsWrite);
                var s3 = safeSave("txns", transactions, allowTxWrite);
                var connsCount = Array.isArray(connections) ? connections.length : 0;
                var txCount = Array.isArray(transactions) ? transactions.length : 0;
                var parts = String(saveSignal).split(":");
                var deltaAppended = (parts.length >= 3) ? parseInt(parts[2], 10) : null;
                console.log("prefix:", pfx);
                console.log("action:", action, "allowConnsWrite:", allowConnsWrite, "allowTxWrite:", allowTxWrite);
                console.log("connections:", s1, "count:", connsCount);
                console.log("transactions:", s3, "count:", txCount);
                if (action === "sync") {
                    console.log("[bank-sync] delta appended:", Number.isFinite(deltaAppended) ? deltaAppended : "n/a");
                }
                console.log("[bank-save] explicit:", saveSignal,
                            "conns:", s1,
                            "txs:", s3);
            } catch(e) {
                console.error("Bank data save error:", e);
            } finally {
                console.groupEnd();
            }
            return "";
        }
        """,
        Output("bs-save-result", "children"),
        Input("bs-save-trigger", "children"),
        [State("bs-connections-store", "data"),
         State("bs-transactions-cache", "data"),
         State("current-user-store", "data")],
        prevent_initial_call=True,
    )


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

    # ─── 0g. "Open Settings" link in warnings → trigger settings modal ──
    app.clientside_callback(
        """
        function(n) {
            if (n) {
                // Programmatically click the hidden settings-link trigger
                var btn = document.getElementById("open-settings-link");
                if (btn) btn.click();
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("open-settings-link-warning", "n_clicks"),
        Input("open-settings-link-warning", "n_clicks"),
        prevent_initial_call=True,
    )

    # ─── 0h. AI categorisation start log (browser console) ────────────
    app.clientside_callback(
        """
        function(n, txs) {
            if (!n) return "";
            var all = Array.isArray(txs) ? txs : [];
            var uncategorised = all.filter(function(t) {
                return !(t && t._category);
            }).length;
            var batchSize = 80;
            var batches = Math.ceil(uncategorised / batchSize);
            console.log("[ai-categorise] started; uncategorised:", uncategorised,
                        "batch_size:", batchSize,
                        "estimated_batches:", batches);
            return "";
        }
        """,
        Output("bs-ai-log-trigger", "children"),
        Input("ai-categorise-btn", "n_clicks"),
        State("bs-transactions-cache", "data"),
        prevent_initial_call=True,
    )

    # ─── 1. Load institutions when country changes ─────────────────────
    @app.callback(
        Output("bank-institution-select", "options"),
        Input("bank-country-select", "value"),
        State("lang-store", "data"),
    )
    def load_institutions_for_country(country, lang_data):
        lang = get_lang(lang_data)
        if not country or not has_credentials():
            return [{"label": t("bs.bank_not_configured", lang), "value": ""}]
        institutions = list_institutions(country)
        if not institutions:
            return [{"label": t("bs.no_banks_found", lang), "value": ""}]
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
         Output("bs-connections-store", "data", allow_duplicate=True),
         Output("bs-save-trigger", "children", allow_duplicate=True)],
        Input("connect-bank-btn", "n_clicks"),
        [State("bank-country-select", "value"),
         State("bank-institution-select", "value"),
         State("bs-connections-store", "data"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def start_bank_connection(n, country, institution_id, connections, lang_data):
        lang = get_lang(lang_data)
        if not n:
            raise PreventUpdate
        if not has_credentials():
            return (
                dbc.Alert(t("bs.not_configured_creds", lang),
                          color="warning", className="small py-1"),
                no_update, no_update, no_update,
            )
        if not institution_id:
            return (
                dbc.Alert(t("bs.select_bank_first", lang),
                          color="warning", className="small py-1"),
                no_update, no_update, no_update,
            )

        conn = create_connection(market=country or "DE",
                                 institution_id=institution_id)
        if not conn:
            return (
                dbc.Alert(t("bs.conn_failed", lang),
                          color="danger", className="small py-1"),
                no_update, no_update, no_update,
            )

        # Append to connections store (client-side)
        connections = list(connections or [])
        connections.append(conn)

        link = conn.get("link", "")
        req_id = conn.get("requisition_id", "")

        feedback = html.Div([
            dbc.Alert([
                html.I(className="bi bi-box-arrow-up-right me-2"),
                html.Strong(t("bs.bank_auth_ready", lang)),
                html.P([
                    t("bs.auth_instructions", lang),
                ], className="mb-2 small"),
                html.A(
                    [html.I(className="bi bi-bank me-1"),
                     t("bs.open_bank_auth", lang)],
                    href=link, target="_blank",
                    className="btn btn-primary btn-sm me-2",
                ),
                dbc.Button(
                    [html.I(className="bi bi-check-circle me-1"),
                     t("bs.auth_complete", lang)],
                    id="auth-complete-btn",
                    color="success", size="sm",
                    className="mt-2", n_clicks=0,
                ),
            ], color="info", className="mt-2"),
        ])
        return feedback, req_id, connections, f"connect:{time.time()}"

    # ─── 4. After auth complete → update connection, auto-sync ─────────
    @app.callback(
        [Output("connected-accounts-body", "children", allow_duplicate=True),
         Output("bs-connections-store", "data", allow_duplicate=True),
         Output("bs-transactions-cache", "data", allow_duplicate=True),
         Output("tx-sync-feedback", "children", allow_duplicate=True),
         Output("bs-save-trigger", "children", allow_duplicate=True)],
        Input("auth-complete-btn", "n_clicks"),
        [State("bs-active-requisition", "data"),
         State("bs-connections-store", "data"),
         State("bs-transactions-cache", "data"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def after_auth_complete(n, requisition_id, connections, cached_txs, lang_data):
        lang = get_lang(lang_data)
        if not n:
            raise PreventUpdate

        connections = list(connections or [])
        cached_txs = list(cached_txs or [])

        if not requisition_id:
            return no_update, no_update, no_update, no_update, no_update

        # Poll requisition status
        result = complete_connection(requisition_id)
        if not result or result["status"] != "LN":
            return (
                dbc.Alert(
                    t("bs.not_yet_linked", lang),
                    color="warning", className="small py-1",
                ),
                no_update, no_update, no_update, no_update,
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
                    t("bs.no_accounts_yet", lang),
                    color="warning", className="small py-1",
                ),
                connections, no_update, no_update, f"auth-complete:{time.time()}",
            )

        # Auto-sync transactions for new accounts (append-only delta)
        sync_feedback = no_update
        if new_accounts:
            for aid in new_accounts:
                # Existing txs for this account stay untouched.
                existing = [t for t in cached_txs
                            if t.get("_account_id") == aid]

                merged = sync_transactions(aid, existing)
                delta_new = _append_only_newer_transactions(existing, merged)
                for tx in delta_new:
                    tx["_account_id"] = aid

                cached_txs.extend(delta_new)

            sync_feedback = dbc.Alert(
                t("bs.auto_synced", lang).format(n_acct=len(new_accounts), n_tx=len(cached_txs)),
                color="success", className="small py-1 mb-0",
            )

        accounts_ui = html.Div([_account_item(a) for a in accounts])
        return (
            accounts_ui,
            connections,
            cached_txs,
            sync_feedback,
            f"auth-complete:{time.time()}",
        )

    # ─── 5. Refresh connected accounts ─────────────────────────────────
    @app.callback(
        Output("connected-accounts-body", "children"),
        [Input("refresh-accounts-btn", "n_clicks"),
         Input("bank-connections-modal", "is_open")],
        [State("bs-connections-store", "data"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def refresh_accounts(n, modal_open, connections, lang_data):
        lang = get_lang(lang_data)
        if modal_open is False and ctx.triggered_id == "bank-connections-modal":
            raise PreventUpdate

        account_ids = _collect_account_ids(connections)
        if not account_ids:
            return html.P(
                t("bs.no_accounts", lang),
                className="text-muted small text-center py-3",
            )

        accounts = fetch_accounts(account_ids)
        if not accounts:
            return html.P(
                t("bs.no_accounts", lang),
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
         Output("tx-category-filter", "value", allow_duplicate=True),
         Output("tx-account-filter", "value", allow_duplicate=True),
         Output("tx-direction-filter", "value", allow_duplicate=True),
         Output("tx-category-donut", "figure"),
         Output("bs-save-trigger", "children", allow_duplicate=True)],
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
         State("api_key_store", "data"),
         State("lang-store", "data")],
        prevent_initial_call='initial_duplicate',
    )
    def sync_and_filter_transactions(
        sync_clicks, filter_text, cat_filter, acct_filter, dir_filter,
        date_from, date_to, cached_txs,
        connections, rules, api_key_data, lang_data,
    ):
        lang = get_lang(lang_data)
        triggered = ctx.triggered_id
        all_txs = list(cached_txs or [])
        feedback = no_update
        store_update = no_update
        save_trigger = no_update

        # ── Sync button pressed ──
        if triggered == "sync-transactions-btn" and sync_clicks:
            account_ids = _collect_account_ids(connections)
            if not account_ids:
                feedback = dbc.Alert(
                    t("bs.no_accounts_sync", lang),
                    color="warning", className="small py-1 mb-0",
                )
            else:
                updated_all = list(all_txs)
                total_new = 0
                rules_list = rules or []

                for aid in account_ids:
                    existing = [tx_ for tx_ in all_txs
                                if tx_.get("_account_id") == aid]
                    merged = sync_transactions(aid, existing)

                    delta_new = _append_only_newer_transactions(existing, merged)
                    for tx in delta_new:
                        tx["_account_id"] = aid

                    if delta_new and rules_list:
                        delta_new = apply_rules(delta_new, rules_list)

                    updated_all.extend(delta_new)
                    total_new += len(delta_new)

                all_txs = updated_all
                store_update = all_txs
                save_trigger = f"sync:{time.time()}:{total_new}"

                feedback = dbc.Alert(
                    t("bs.synced_n", lang).format(n_tx=len(all_txs), n_acct=len(account_ids)),
                    color="success", className="small py-1 mb-0",
                )

        # ── Empty state ──
        if not all_txs:
            import plotly.graph_objects as go
            empty_fig = go.Figure()
            empty_fig.update_layout(
                annotations=[dict(text=t("bs.no_data", lang), x=0.5, y=0.5,
                                  font_size=14, showarrow=False)],
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            return (
                html.P(t("bs.no_tx_yet", lang),
                       className="text-muted small text-center py-4"),
                feedback, store_update,
                [],
                [],
                no_update, no_update, no_update,
                empty_fig,
                save_trigger,
            )

        # ── Normalise ──
        normalised = [normalize_transaction(tx) for tx in all_txs]

        # ── Build filter dropdowns ──
        cats = sorted(set(n["category"] for n in normalised if n["category"]))
        cat_options = [{"label": c, "value": c} for c in cats]

        # Account labels: use _account_name if available, else masked ID
        acct_map = {}
        for tx in all_txs:
            aid = tx.get("_account_id", "")
            if aid and aid not in acct_map:
                name = tx.get("_account_name", "")
                acct_map[aid] = name or f"****{aid[-4:]}"
        acct_options = [{"label": acct_map[a], "value": a}
                        for a in sorted(acct_map.keys())]

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
        selected_categories = set(cat_filter or [])
        if selected_categories:
            filtered = [n for n in filtered
                        if n.get("category") in selected_categories]

        selected_accounts = set(acct_filter or [])
        if selected_accounts:
            # Need to match back to raw txs
            matching_ids = set()
            for tx in all_txs:
                if tx.get("_account_id") in selected_accounts:
                    norm = normalize_transaction(tx)
                    matching_ids.add(norm["id"])
            filtered = [n for n in filtered if n["id"] in matching_ids]

        selected_dirs = set(dir_filter or [])
        if selected_dirs:
            filtered = [
                n for n in filtered
                if (("in" in selected_dirs and n["amount"] > 0)
                    or ("out" in selected_dirs and n["amount"] < 0))
            ]

        # ── Donut chart ──
        donut_fig = _build_donut(filtered, lang)

        # ── Rows ──
        if not filtered:
            rows = html.P(t("bs.no_tx_match", lang),
                          className="text-muted small text-center py-3")
        else:
            rows = html.Div(
                [_transaction_row(n, i) for i, n in enumerate(filtered[:200])],
                style={"maxHeight": "500px", "overflowY": "auto"},
            )
            if len(filtered) > 200:
                rows = html.Div([
                    rows,
                    html.P(t("bs.showing_n", lang).format(n=len(filtered)),
                           className="text-muted small text-center mt-2"),
                ])

        # ── Auto-select all when triggered by non-filter action ──
        _filter_ids = {"tx-category-filter", "tx-account-filter",
                       "tx-direction-filter", "tx-filter-input",
                       "tx-date-range"}
        if triggered not in _filter_ids:
            cat_val = [o["value"] for o in cat_options]
            acct_val = [o["value"] for o in acct_options]
            dir_val = ["in", "out"]
        else:
            cat_val = no_update
            acct_val = no_update
            dir_val = no_update

        return (
            rows,
            feedback,
            store_update,
            cat_options,
            acct_options,
            cat_val,
            acct_val,
            dir_val,
            donut_fig,
            save_trigger,
        )

    # ─── 7. AI categorise ──────────────────────────────────────────────
    @app.callback(
        Output("tx-sync-feedback", "children", allow_duplicate=True),
        Input("ai-categorise-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def ai_categorise_loading_feedback(n):
        if not n:
            raise PreventUpdate
        return dbc.Alert(
            "Categorising your transactions, please wait...",
            color="info",
            className="small py-1 mb-0",
        )

    @app.callback(
        [Output("transactions-container", "children", allow_duplicate=True),
         Output("tx-sync-feedback", "children", allow_duplicate=True),
         Output("bs-transactions-cache", "data", allow_duplicate=True),
         Output("bs-save-trigger", "children", allow_duplicate=True)],
        Input("ai-categorise-btn", "n_clicks"),
        [State("bs-transactions-cache", "data"),
         State("api_key_store", "data"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def ai_categorise(n, cached_txs, api_key_data, lang_data):
        lang = get_lang(lang_data)
        if not n or not cached_txs:
            raise PreventUpdate

        api_key = (api_key_data or {}).get("api_key", "")
        if not api_key:
            return (
                no_update,
                dbc.Alert([
                    html.I(className="bi bi-exclamation-triangle me-1"),
                    t("bs.set_api_key", lang),
                    html.A(t("bs.settings", lang), href="#", className="alert-link",
                           style={"cursor": "pointer", "textDecoration": "underline"},
                           id={"type": "open-settings-inline", "index": "ai-cat"}),
                    t("bs.first", lang),
                ], color="warning", className="small py-1 mb-0"),
                no_update,
                no_update,
            )

        uncategorised_count = sum(
            1 for tx in cached_txs if not tx.get("_category")
        )
        if uncategorised_count == 0:
            return (
                no_update,
                dbc.Alert(t("bs.all_categorised", lang),
                          color="info", className="small py-1 mb-0"),
                no_update,
                no_update,
            )

        try:
            cached_txs = categorise_transactions_batch(cached_txs, api_key)
        except Exception as e:
            err_str = str(e)
            if "invalid_api_key" in err_str or "401" in err_str:
                msg = t("bs.invalid_api_key", lang)
            else:
                msg = t("bs.cat_error", lang).format(msg=err_str[:100])
            return (
                no_update,
                dbc.Alert(msg, color="danger", className="small py-1 mb-0"),
                no_update,
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
            dbc.Alert(t("bs.categorised_n", lang).format(n=cat_count),
                      color="success", className="small py-1 mb-0"),
            cached_txs,
            f"ai-categorise:{time.time()}",
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
        trig = ctx.triggered_id
        if trig == "open-add-rule-modal-btn":
            return True
        if trig in ("cancel-rule-btn", "confirm-add-rule-btn"):
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
         State("bs-rules-store", "data"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def create_rule_cb(n, name, category, pattern, amount, tolerance,
                       freq, rules, lang_data):
        lang = get_lang(lang_data)
        if not n:
            raise PreventUpdate
        if not name or not pattern:
            return (
                no_update,
                dbc.Alert(t("bs.name_pattern_required", lang),
                          color="warning", className="small py-1 mb-0"),
                no_update,
            )

        expected_amount = float(amount) if amount else None
        tol = float(tolerance) / 100 if tolerance else 0.1
        freq_days = int(freq) if freq else 30

        selected_categories = [c for c in (category or []) if c]
        primary_category = selected_categories[0] if selected_categories else "Other"

        rule = make_rule(name, pattern, primary_category,
                         expected_amount, tol, freq_days)
        rule["match_categories"] = selected_categories

        rules = list(rules or [])
        rules.append(rule)

        items = [_rule_item(r, lang) for r in rules]
        ui = (html.Div(items) if items
              else html.P(t("bs.no_rules", lang), className="text-muted small "
                          "text-center py-3"))
        return ui, "", rules

    # ─── 10. Delete a rule (from browser store) ───────────────────────
    @app.callback(
        [Output("rules-container", "children"),
         Output("bs-rules-store", "data", allow_duplicate=True)],
        Input({"type": "delete-rule-btn", "index": ALL}, "n_clicks"),
        [State("bs-rules-store", "data"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def remove_rule(n_clicks_list, rules, lang_data):
        lang = get_lang(lang_data)
        if not any(n_clicks_list):
            raise PreventUpdate
        triggered = ctx.triggered_id
        if not triggered or not isinstance(triggered, dict):
            raise PreventUpdate

        rule_id = triggered["index"]
        rules = [r for r in (rules or []) if r["id"] != rule_id]

        if not rules:
            return (
                html.P(t("bs.no_rules", lang),
                       className="text-muted small text-center py-2 mb-0"),
                rules,
            )
        return html.Div([_rule_item(r, lang) for r in rules]), rules

    # ─── 11. Load rules on page visit ─────────────────────────────────
    @app.callback(
        Output("rules-container", "children", allow_duplicate=True),
        Input("bs-rules-store", "data"),
        State("lang-store", "data"),
        prevent_initial_call='initial_duplicate',
    )
    def render_rules(rules, lang_data):
        lang = get_lang(lang_data)
        rules = rules or []
        if not rules:
            return html.P(
                t("bs.no_rules", lang),
                className="text-muted small text-center py-2 mb-0",
            )
        return html.Div([_rule_item(r, lang) for r in rules])

    # ─── 12. Monitoring panel ─────────────────────────────────────────
    @app.callback(
        Output("monitoring-container", "children"),
        [Input("monitoring-months-select", "value"),
         Input("bs-rules-store", "data"),
         Input("bs-transactions-cache", "data")],
        State("lang-store", "data"),
    )
    def update_monitoring(months, rules, cached_txs, lang_data):
        lang = get_lang(lang_data)
        rules = rules or []
        txs = cached_txs or []
        if not rules and not txs:
            return html.P(
                t("bs.add_rules_first", lang),
                className="text-muted small text-center py-2 mb-0",
            )

        months_back = int(months) if months else 6
        summaries = compute_monitoring_summary(txs, rules, months_back)
        if not summaries:
            return html.P(
                t("bs.no_rules_monitor", lang),
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
                html.Div(t("bs.on_track", lang), className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(str(overdue_count),
                         className="fs-5 fw-bold text-warning"),
                html.Div(t("bs.overdue", lang), className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(str(missing_count),
                         className="fs-5 fw-bold text-danger"),
                html.Div(t("bs.missing", lang), className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Div(f"€{total_cumulative:,.0f}",
                         className="fs-5 fw-bold"),
                html.Div(t("bs.cumulative", lang), className="text-muted",
                         style={"fontSize": "0.7rem"}),
            ], className="text-center"), width=3),
        ], className="mb-2 py-2 bg-light rounded")

        return html.Div([
            stats,
            html.Div([_monitoring_row(s, lang) for s in summaries]),
        ])
