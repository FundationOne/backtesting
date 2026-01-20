"""
Portfolio Analysis Page
Analyze your Trade Republic portfolio with performance charts and metrics
Inspired by Parqet's design
"""

import dash
from dash import html, dcc, Input, Output, State, callback, dash_table, ctx, no_update
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from pathlib import Path
import json
import math
from collections import OrderedDict

# Import the TR connector component
from components.tr_connector import create_tr_connector_card, register_tr_callbacks
from components.tr_api import fetch_all_data, is_connected, reconnect
from components.benchmark_data import get_benchmark_data, initialize_benchmarks, BENCHMARKS

# Initialize benchmark cache on module load
initialize_benchmarks()


# Small in-memory cache to avoid re-building identical figures on page refresh.
# Keyed by (cached_at, chart_type, range, benchmarks, include_benchmarks).
_FIG_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_FIG_CACHE_MAX = 24
_DEBUG_WRITE_COMPARE_SUMMARY = False


def _fig_cache_get(key: str):
    try:
        fig_dict = _FIG_CACHE.get(key)
        if fig_dict is None:
            return None
        _FIG_CACHE.move_to_end(key)
        return fig_dict
    except Exception:
        return None


def _fig_cache_set(key: str, fig_dict: dict):
    try:
        _FIG_CACHE[key] = fig_dict
        _FIG_CACHE.move_to_end(key)
        while len(_FIG_CACHE) > _FIG_CACHE_MAX:
            _FIG_CACHE.popitem(last=False)
    except Exception:
        pass


def fetch_benchmark_data(symbol, start_date, end_date):
    """Fetch historical data for a benchmark using cached data."""
    try:
        # Use cached benchmark data
        df = get_benchmark_data(symbol, start_date, end_date)
        if df is not None and len(df) > 0:
            df = df.reset_index()
            return df[["Date", "Close"]]
        return None
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None


# TR Connect Modal
tr_connect_modal = dbc.Modal([
    dbc.ModalHeader([
        html.Div([
            html.I(className="bi bi-bank me-2"),
            "Connect to Trade Republic"
        ], className="d-flex align-items-center")
    ], close_button=True),
    dbc.ModalBody([
        create_tr_connector_card(),
    ]),
], id="tr-connect-modal", size="md", centered=True, className="tr-modal", is_open=False)


def create_metric_card(title, value_id, subtitle_id=None, icon=None, color_class=""):
    """Create a metric card component."""
    return html.Div([
        html.Div([
            html.Div(title, className="metric-label"),
            html.Div(id=value_id, className=f"metric-value sensitive {color_class}", children="--"),
            html.Div(
                id=subtitle_id,
                className="metric-subtitle sensitive",
                children="",
            ) if subtitle_id else html.Div(
                className="metric-subtitle metric-subtitle-placeholder",
                children="",
            ),
        ], className="metric-content"),
    ], className="metric-card")


def get_position_asset_class(position):
    for key in ("assetClass", "asset_class", "assetType", "type", "category", "instrumentType"):
        value = position.get(key)
        if value:
            return str(value)
    return "Other"


# Layout for the analysis page
layout = dbc.Container([
    # Page Header
    html.Div([
        html.Div([
            html.H4([
                html.I(className="bi bi-pie-chart me-2"),
                "Portfolio Analysis"
            ], className="mb-0"),
            html.P("Trade Republic Portfolio Overview", className="text-muted mb-0 mt-1"),
        ], className="d-flex flex-column"),
        # Sync button + privacy toggle
        html.Div([
            dbc.Button([
                html.I(className="bi bi-arrow-repeat me-2"),
                "Sync"
            ], id="sync-tr-data-btn", color="outline-primary", size="sm", className="me-2", n_clicks=0),
            dbc.Button([
                html.I(className="bi bi-eye-slash me-2"),
                "Hide Values"
            ], id="toggle-privacy-btn", color="outline-secondary", size="sm", className="me-2", n_clicks=0),
        ], className="d-flex align-items-center"),
    ], className="page-header d-flex justify-content-between align-items-start"),

    # Global filters
    dbc.Row([
        dbc.Col([
            dcc.Dropdown(
                id="global-timeframe",
                options=[
                    {"label": "1M", "value": "1m"},
                    {"label": "3M", "value": "3m"},
                    {"label": "6M", "value": "6m"},
                    {"label": "YTD", "value": "ytd"},
                    {"label": "1Y", "value": "1y"},
                    {"label": "MAX", "value": "max"},
                ],
                value="1y",
                clearable=False,
                className="compact-dropdown",
            )
        ], md=2, className="mb-2"),
        dbc.Col([
            dcc.Dropdown(
                id="asset-class-filter",
                options=[{"label": "All Asset Classes", "value": "all"}],
                value="all",
                clearable=False,
                className="compact-dropdown",
            )
        ], md=3, className="mb-2"),
        dbc.Col([
            dcc.Dropdown(
                id="benchmark-selector",
                options=[
                    {"label": info["name"], "value": symbol}
                    for symbol, info in BENCHMARKS.items()
                ],
                value=["^GSPC", "^GDAXI", "URTH"],
                multi=True,
                clearable=False,
                className="compact-dropdown",
            )
        ], md=7, className="mb-2"),
    ], className="mb-2"),
    
    # Top Summary Row (Parqet-style)
    dbc.Row([
        # Donut Chart Card
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dcc.Graph(id="holdings-donut-chart", 
                              config={"displayModeBar": False},
                              style={"height": "260px"}),
                ], className="py-0 px-0"),
            ], className="card-modern h-100 sensitive"),
        ], md=3, className="mb-3"),
        
        # Portfolio Summary + Metrics
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Div("Portfolio Value", className="text-muted small"),
                                html.Div(id="portfolio-total-value", className="fs-2 fw-bold portfolio-hero-value sensitive sensitive-strong", 
                                         children="€0.00"),
                                html.Div(id="portfolio-total-change", className="fs-6 sensitive", children=""),
                                html.Div(id="data-freshness", className="text-muted small mt-2", children=""),
                                html.Div([
                                    html.Span("Positions", className="text-muted small"),
                                    html.Span(id="metric-positions", className="portfolio-positions-value sensitive", children="--"),
                                ], className="portfolio-positions-inline"),
                            ], className="py-1"),
                        ], md=4, className="mb-2"),
                        dbc.Col([
                            dbc.Row([
                                dbc.Col([
                                    create_metric_card("Invested", "metric-invested"),
                                ], width=4, className="mb-2"),
                                dbc.Col([
                                    create_metric_card("Profit/Loss", "metric-profit", "metric-profit-pct"),
                                ], width=4, className="mb-2"),
                                dbc.Col([
                                    create_metric_card("Cash", "metric-cash"),
                                ], width=4, className="mb-2"),
                            ]),
                            dbc.Row([
                                dbc.Col([
                                    create_metric_card("1M Return", "metric-1m-return"),
                                ], width=3),
                                dbc.Col([
                                    create_metric_card("3M Return", "metric-3m-return"),
                                ], width=3),
                                dbc.Col([
                                    create_metric_card("YTD Return", "metric-ytd-return"),
                                ], width=3),
                                dbc.Col([
                                    create_metric_card("Total Return", "metric-total-return"),
                                ], width=3),
                            ]),
                        ], md=8, className="mb-2"),
                    ]),
                ]),
            ], className="card-modern h-100"),
        ], md=9, className="mb-3"),
    ], className="portfolio-top-summary"),
    
    # Charts Row (Value/Drawdown + Performance)
    dbc.Row([
        # Value / Drawdown Chart
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    # Chart Type Tabs
                    dbc.Tabs([
                        dbc.Tab(label="Value", tab_id="tab-value"),
                        dbc.Tab(label="Drawdown", tab_id="tab-drawdown"),
                    ], id="chart-tabs", active_tab="tab-value", className="mb-2"),
                    
                    # Main Chart
                    dcc.Loading(
                        dcc.Graph(
                            id="main-portfolio-chart-v2",
                            config={
                                "displayModeBar": False,
                                "displaylogo": False,
                                "scrollZoom": False,
                                "doubleClick": "reset",
                                "responsive": True,
                            },
                            style={"height": "330px"},
                        ),
                        type="circle",
                        color="#6366f1"
                    ),
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=7, className="mb-3"),
        
        # Performance Chart
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-graph-up-arrow me-2"),
                    "Performance"
                ], className="card-header-modern"),
                dbc.CardBody([
                    dcc.Loading(
                        dcc.Graph(
                            id="performance-chart",
                            config={
                                "displayModeBar": False,
                                "displaylogo": False,
                                "scrollZoom": False,
                                "doubleClick": "reset",
                                "responsive": True,
                            },
                            style={"height": "330px"},
                        ),
                        type="circle",
                        color="#10b981"
                    ),
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=5, className="mb-3"),
    ]),

    # Lower Row (Holdings + Comparison)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-list-ul me-2"),
                    "Holdings",
                    dbc.Badge(id="holdings-count", children="0", className="ms-2", color="primary", pill=True),
                ], className="card-header-modern d-flex align-items-center"),
                dbc.CardBody([
                    html.Div(id="holdings-list", style={"maxHeight": "320px", "overflowY": "auto"}),
                ], className="py-2 px-2"),
            ], className="card-modern"),
        ], md=4, className="mb-3"),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-bar-chart-line me-2"),
                    "Performance Comparison"
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.Div(id="comparison-table-container"),
                ], className="py-2"),
            ], className="card-modern"),
        ], md=8, className="mb-3"),
    ]),

    # Activity + Top Movers + Returns Summary (Parqet-style)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-bar-chart me-2"),
                    "Rendite"
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.Div(id="rendite-breakdown")
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=4, className="mb-3"),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-clock-history me-2"),
                    "Letzte Aktivitäten"
                ], className="card-header-modern d-flex align-items-center justify-content-between"),
                dbc.CardBody([
                    html.Div(id="recent-activities-list")
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=4, className="mb-3"),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-graph-up me-2"),
                    "Top Mover"
                ], className="card-header-modern d-flex align-items-center justify-content-between"),
                dbc.CardBody([
                    html.Div(id="top-movers-list")
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=4, className="mb-3"),
    ]),

    # Securities Table
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-table me-2"),
                    "Wertpapiere"
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.Div(id="securities-table-container")
                ], className="py-2"),
            ], className="card-modern"),
        ], md=12, className="mb-3"),
    ]),
    
    # TR Connect Modal
    tr_connect_modal,
    
    # Hidden stores - portfolio-data-store and tr-encrypted-creds are in main.py layout
    dcc.Store(id="selected-range", data="max"),
    dcc.Store(id="privacy-mode", data=False),
    dcc.Store(id="tr-session-data", storage_type="session"),  # Current session only
    dcc.Store(id="tr-auth-step", data="initial"),
    dcc.Store(id="tr-check-creds-trigger", data=0),
    dcc.Interval(id="load-cached-data-interval", interval=500, max_intervals=1),
    html.Div(id="comparison-page", style={"display": "none"}),
    
    # (debug divs removed)
    
], fluid=True, className="portfolio-analysis-page", id="portfolio-analysis-root")


def register_callbacks(app):
    """Register callbacks for the portfolio analysis page."""
    
    # Register TR connector callbacks
    register_tr_callbacks(app)
    
    # (debug clientside callbacks removed)
    
    # Load from server cache if browser localStorage is empty
    @app.callback(
        Output("portfolio-data-store", "data", allow_duplicate=True),
        Input("load-cached-data-interval", "n_intervals"),
        State("portfolio-data-store", "data"),
        prevent_initial_call='initial_duplicate'
    )
    def load_from_server_cache(n_intervals, current_data):
        """Load portfolio data from server cache.
        
        ALWAYS prefer server cache over browser localStorage to ensure
        fresh data after recalculations (e.g., correct EUR values).
        """
        from components.tr_api import get_cached_portfolio
        
        # Always load from server cache - it has the latest recalculated values
        cached = get_cached_portfolio()
        
        if cached and cached.get("success"):
            # ALWAYS use server cache. Browser storage is not authoritative and can be stale/wrong.
            # Do not trigger history rebuilds here; page load must be fast and stable.
            return json.dumps(cached)
        
        return no_update
    
    # Modal: auto-open on first load if no data; close on successful sync
    @app.callback(
        Output("tr-connect-modal", "is_open"),
        [Input("portfolio-data-store", "data"),
         Input("load-cached-data-interval", "n_intervals")],
        [State("tr-connect-modal", "is_open"),
         State("tr-encrypted-creds", "data")],
        prevent_initial_call=False
    )
    def toggle_tr_modal(portfolio_data, n_intervals, is_open, encrypted_creds):
        triggered = ctx.triggered_id
        
        # Close modal when data loads successfully
        if triggered == "portfolio-data-store" and portfolio_data:
            try:
                data = json.loads(portfolio_data)
                if data.get("success"):
                    return False
            except:
                pass
        
        # On initial load, if no data and no credentials, prompt login
        if triggered == "load-cached-data-interval":
            if not portfolio_data and not encrypted_creds:
                return True
        
        return is_open
    
    # Sync button: if connected → sync; if not → open login modal
    @app.callback(
        [Output("portfolio-data-store", "data", allow_duplicate=True),
         Output("sync-tr-data-btn", "children"),
         Output("sync-tr-data-btn", "disabled"),
         Output("tr-connect-modal", "is_open", allow_duplicate=True)],
        Input("sync-tr-data-btn", "n_clicks"),
        [State("tr-encrypted-creds", "data"),
         State("tr-connect-modal", "is_open")],
        prevent_initial_call=True,
        running=[
            (Output("sync-tr-data-btn", "disabled"), True, False),
            (Output("sync-tr-data-btn", "children"), [html.I(className="bi bi-arrow-repeat spin me-2"), "Syncing..."], [html.I(className="bi bi-arrow-repeat me-2"), "Sync"]),
        ]
    )
    def sync_data(n_clicks, encrypted_creds, modal_open):
        if not n_clicks:
            raise PreventUpdate
        
        from components.tr_api import fetch_all_data, reconnect, is_connected
        
        # If not connected, try silent reconnect with stored creds
        if not is_connected() and encrypted_creds:
            reconnect(encrypted_creds)
        
        # Still not connected? Open login modal
        if not is_connected():
            return no_update, [html.I(className="bi bi-arrow-repeat me-2"), "Sync"], False, True
        
        # Connected — fetch data (uses server cache if fresh)
        data = fetch_all_data()
        if data.get("success"):
            return json.dumps(data), [html.I(className="bi bi-check-circle me-2"), "Synced!"], False, False
        
        return no_update, [html.I(className="bi bi-x-circle me-2"), "Sync Failed"], False, modal_open
    
    # Update metrics when data changes
    @app.callback(
        [Output("portfolio-total-value", "children"),
         Output("portfolio-total-change", "children"),
         Output("portfolio-total-change", "className"),
         Output("data-freshness", "children"),
         Output("metric-invested", "children"),
         Output("metric-profit", "children"),
         Output("metric-profit", "className"),
         Output("metric-profit-pct", "children"),
         Output("metric-cash", "children"),
         Output("metric-positions", "children"),
         Output("holdings-count", "children"),
         Output("holdings-list", "children")],
        [Input("portfolio-data-store", "data"),
         Input("asset-class-filter", "value")],
        prevent_initial_call=False
    )
    def update_metrics(data_json, asset_class):
        if not data_json:
            empty = ("€0.00", "", "fs-5", "No data synced", "€0.00", "€0.00", "metric-value", "", "€0.00", "0", "0", 
                     html.Div("No data - connect to Trade Republic and sync", className="text-muted text-center py-4"))
            return empty
        
        try:
            data = json.loads(data_json)
            if not data.get("success") or not data.get("data"):
                raise ValueError("No data")
            
            portfolio = data["data"]
            total_value = portfolio.get("totalValue", 0)
            invested = portfolio.get("investedAmount", 0)
            profit = portfolio.get("totalProfit", 0)
            profit_pct = portfolio.get("totalProfitPercent", 0)
            cash = portfolio.get("cash", 0)
            positions = portfolio.get("positions", [])
            selected_class = asset_class or "all"
            if selected_class != "all":
                positions = [p for p in positions if get_position_asset_class(p) == selected_class]
            
            # Get sync timestamp
            cached_at = data.get("cached_at", "")
            if cached_at:
                try:
                    from datetime import datetime
                    sync_time = datetime.fromisoformat(cached_at)
                    freshness = f"Last synced: {sync_time.strftime('%d %b %Y, %H:%M')}"
                except:
                    freshness = "Synced"
            else:
                freshness = "Just synced"
            
            # Calculate returns from history
            history = portfolio.get("history", [])
            
            # Format values
            value_str = f"€{total_value:,.2f}"
            invested_str = f"€{invested:,.2f}"
            profit_str = f"{'+'if profit >= 0 else ''}€{profit:,.2f}"
            profit_pct_str = f"{'+'if profit_pct >= 0 else ''}{profit_pct:.2f}%"
            cash_str = f"€{cash:,.2f}"
            positions_str = str(len(positions))
            
            # Change styling
            change_class = "fs-5 text-success sensitive" if profit >= 0 else "fs-5 text-danger sensitive"
            profit_class = "metric-value text-success sensitive" if profit >= 0 else "metric-value text-danger sensitive"
            change_str = html.Span([
                html.I(className=f"bi bi-{'arrow-up' if profit >= 0 else 'arrow-down'}-right me-1"),
                f"{'+'if profit >= 0 else ''}€{abs(profit):,.2f} ({profit_pct:+.2f}%)"
            ])
            
            # Build holdings list
            holdings_items = []
            for pos in sorted(positions, key=lambda x: x.get("value", 0), reverse=True):
                name = pos.get("name", "Unknown")
                value = pos.get("value", 0)
                qty = pos.get("quantity", 0)
                pos_profit = pos.get("profit", 0)
                avg_buy = pos.get("averageBuyIn", 0)
                
                profit_color = "text-success" if pos_profit >= 0 else "text-danger"
                
                holdings_items.append(
                    html.Div([
                        html.Div([
                            html.Div(name[:30] + ("..." if len(name) > 30 else ""), 
                                     className="fw-medium small", title=name),
                            html.Div(f"{qty:.4g} × €{avg_buy:.2f}", className="text-muted small"),
                        ], className="flex-grow-1"),
                        html.Div([
                            html.Div(f"€{value:,.2f}", className="small fw-medium text-end sensitive"),
                            html.Div(f"{'+'if pos_profit >= 0 else ''}€{pos_profit:,.2f}", 
                                     className=f"small {profit_color} text-end sensitive"),
                        ]),
                    ], className="d-flex justify-content-between align-items-center py-2 border-bottom holding-item")
                )
            
            holdings_list = html.Div(holdings_items) if holdings_items else html.Div(
                "No holdings", className="text-muted text-center py-3"
            )
            
            return (value_str, change_str, change_class, freshness, invested_str, profit_str, 
                    profit_class, profit_pct_str, cash_str, positions_str, positions_str, holdings_list)
            
        except Exception as e:
            print(f"Error updating metrics: {e}")
            return ("€0.00", "", "fs-5", "Error loading data", "€0.00", "€0.00", "metric-value", "", "€0.00", "0", "0",
                    html.Div(f"Error: {str(e)}", className="text-danger text-center py-3"))
    
    # Donut chart for holdings breakdown
    @app.callback(
        Output("holdings-donut-chart", "figure"),
        [Input("portfolio-data-store", "data"),
         Input("asset-class-filter", "value")],
        prevent_initial_call=False
    )
    def update_donut_chart(data_json, asset_class):
        # Dark theme colors matching the image
        colors = ['#f97316', '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6', 
                  '#8b5cf6', '#d946ef', '#ec4899', '#ef4444', '#f59e0b', '#84cc16']
        
        fig = go.Figure()
        
        if not data_json:
            # Empty donut
            fig.add_trace(go.Pie(
                values=[1], labels=["No data"], hole=0.7,
                marker=dict(colors=["#374151"]),
                textinfo="none", hoverinfo="none"
            ))
            fig.update_layout(
                showlegend=False, margin=dict(l=20, r=20, t=20, b=20),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                annotations=[dict(text="No data", x=0.5, y=0.5, font_size=14, showarrow=False, font_color="#94a3b8")]
            )
            return fig
        
        try:
            data = json.loads(data_json)
            positions = data.get("data", {}).get("positions", [])
            selected_class = asset_class or "all"
            if selected_class != "all":
                positions = [p for p in positions if get_position_asset_class(p) == selected_class]
            
            if not positions:
                fig.add_trace(go.Pie(values=[1], labels=["Empty"], hole=0.7, marker=dict(colors=["#374151"]), textinfo="none"))
                fig.update_layout(showlegend=False, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)")
                return fig
            
            # Sort by value
            positions = sorted(positions, key=lambda x: x.get("value", 0), reverse=True)
            
            labels = [p.get("name", "Unknown")[:25] for p in positions]
            values = [p.get("value", 0) for p in positions]
            total = sum(values)
            
            # Center text: total portfolio value
            center_name = "Portfolio"
            center_value = f"€{total:,.2f}"
            
            fig.add_trace(go.Pie(
                values=values, labels=labels, hole=0.7,
                marker=dict(colors=colors[:len(values)]),
                textinfo="none",
                hoverinfo="skip",
            ))
            
            fig.update_layout(
                showlegend=False,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                annotations=[
                    dict(text=center_name, x=0.5, y=0.55, font_size=11, showarrow=False, font_color="#94a3b8"),
                    dict(text=center_value, x=0.5, y=0.45, font_size=18, showarrow=False, font_color="#f8fafc", font_weight="bold"),
                ]
            )
            return fig
            
        except Exception as e:
            print(f"Donut chart error: {e}")
            fig.add_trace(go.Pie(values=[1], labels=["Error"], hole=0.7, marker=dict(colors=["#374151"]), textinfo="none"))
            fig.update_layout(showlegend=False, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)")
            return fig
    
    # Time return metrics
    @app.callback(
        [Output("asset-class-filter", "options"),
         Output("asset-class-filter", "value")],
        [Input("portfolio-data-store", "data"),
         State("asset-class-filter", "value")],
        prevent_initial_call=False
    )
    def update_asset_class_options(data_json, current_value):
        options = [{"label": "All Asset Classes", "value": "all"}]
        selected = current_value or "all"

        if not data_json:
            return options, "all"

        try:
            data = json.loads(data_json)
            positions = data.get("data", {}).get("positions", [])
            classes = sorted({get_position_asset_class(p) for p in positions if get_position_asset_class(p)})
            options.extend([{"label": c, "value": c} for c in classes])
            if selected not in {opt["value"] for opt in options}:
                selected = "all"
        except Exception:
            selected = "all"

        return options, selected

    @app.callback(
        [Output("metric-1m-return", "children"),
         Output("metric-1m-return", "className"),
         Output("metric-3m-return", "children"),
         Output("metric-3m-return", "className"),
         Output("metric-ytd-return", "children"),
         Output("metric-ytd-return", "className"),
         Output("metric-total-return", "children"),
         Output("metric-total-return", "className")],
        Input("portfolio-data-store", "data"),
        prevent_initial_call=False
    )
    def update_return_metrics(data_json):
        default = ("--", "metric-value", "--", "metric-value", "--", "metric-value", "--", "metric-value")
        
        if not data_json:
            return default
        
        try:
            data = json.loads(data_json)
            history = data.get("data", {}).get("history", [])
            
            if not history:
                return default
            
            # Convert to dataframe
            df = pd.DataFrame(history)
            if 'date' not in df.columns or 'value' not in df.columns:
                return default
            
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            current_value = df['value'].iloc[-1]
            
            # Get total invested (from latest 'invested' field or fallback to portfolio data)
            total_invested = df['invested'].iloc[-1] if 'invested' in df.columns else df['value'].iloc[-2] if len(df) > 1 else current_value
            
            # Also try getting from portfolio data directly
            portfolio = data.get("data", {})
            if portfolio.get("investedAmount", 0) > 0:
                total_invested = portfolio["investedAmount"]
            
            def calc_return_on_investment(days_ago):
                """Calculate return compared to invested amount at that time."""
                target_date = datetime.now() - timedelta(days=days_ago)
                past_data = df[df['date'] <= target_date]
                if len(past_data) == 0:
                    return 0
                
                # Get invested amount at that point
                invested_then = past_data['invested'].iloc[-1] if 'invested' in past_data.columns else past_data['value'].iloc[-1]
                
                # If invested amount was less than current, calculate growth
                if invested_then > 0 and total_invested > 0:
                    # Calculate how much the portfolio has grown relative to additional investments
                    # Simple approach: (current_value - total_invested) vs (value_then - invested_then)
                    current_profit = current_value - total_invested
                    past_profit = past_data['value'].iloc[-1] - invested_then
                    
                    # Return change in profit relative to current invested
                    if total_invested > 0:
                        return (current_profit - past_profit) / total_invested * 100
                return 0
            
            # YTD: Compare current profit to profit at start of year
            ytd_start = df[df['date'] >= datetime(datetime.now().year, 1, 1)]
            if len(ytd_start) > 0 and 'invested' in df.columns:
                ytd_invested = ytd_start['invested'].iloc[0]
                ytd_value = ytd_start['value'].iloc[0]
                ytd_profit = ytd_value - ytd_invested
                current_profit = current_value - total_invested
                
                if total_invested > 0:
                    ytd_return = (current_profit - ytd_profit) / total_invested * 100
                else:
                    ytd_return = 0
            else:
                ytd_return = 0
            
            # Total return: (current_value - total_invested) / total_invested
            if total_invested > 0:
                total_return = (current_value - total_invested) / total_invested * 100
            else:
                total_return = 0
            
            m1_return = calc_return_on_investment(30)
            m3_return = calc_return_on_investment(90)
            
            def fmt(val):
                sign = "+" if val >= 0 else ""
                return f"{sign}{val:.1f}%"
            
            def cls(val):
                return "metric-value text-success" if val >= 0 else "metric-value text-danger"
            
            return (fmt(m1_return), cls(m1_return), fmt(m3_return), cls(m3_return),
                    fmt(ytd_return), cls(ytd_return), fmt(total_return), cls(total_return))
            
        except Exception as e:
            print(f"Error calculating returns: {e}")
            return default

    # Rendite + Aktivitäten + Top Mover + Wertpapiere
    @app.callback(
        [Output("rendite-breakdown", "children"),
         Output("recent-activities-list", "children"),
         Output("top-movers-list", "children"),
         Output("securities-table-container", "children")],
        [Input("portfolio-data-store", "data"),
         Input("asset-class-filter", "value")],
        prevent_initial_call=False
    )
    def update_rendite_and_lists(data_json, asset_class):
        if not data_json:
            empty_table = dash_table.DataTable(
                data=[],
                columns=[
                    {"name": "Name", "id": "name"},
                    {"name": "Position", "id": "value"},
                    {"name": "Kursgewinn", "id": "profit"},
                    {"name": "Dividenden", "id": "dividends"},
                    {"name": "Realisiert", "id": "realized"},
                    {"name": "Allocation", "id": "allocation"},
                ],
                style_cell={"textAlign": "left", "padding": "8px 12px", "fontFamily": "Inter, sans-serif", "fontSize": "12px", "border": "none"},
                style_header={"fontWeight": "600", "backgroundColor": "#f8fafc", "borderBottom": "1px solid #e5e7eb"},
                style_data={"borderBottom": "1px solid #f3f4f6"},
                style_as_list_view=True,
            )
            return (
                html.Div("No data synced", className="text-muted text-center py-3"),
                html.Div("No recent activity", className="text-muted text-center py-3"),
                html.Div("No movers", className="text-muted text-center py-3"),
                empty_table,
            )

        try:
            data = json.loads(data_json)
            if not data.get("success"):
                raise ValueError("No data")

            portfolio = data.get("data", {})
            positions = portfolio.get("positions", [])
            selected_class = asset_class or "all"
            if selected_class != "all":
                positions = [p for p in positions if get_position_asset_class(p) == selected_class]
            transactions = portfolio.get("transactions", [])

            total_value = float(portfolio.get("totalValue", 0))
            invested = float(portfolio.get("investedAmount", 0))
            cash = float(portfolio.get("cash", 0))
            profit = float(portfolio.get("totalProfit", 0))
            profit_pct = float(portfolio.get("totalProfitPercent", 0))

            def fmt_eur(val):
                sign = "+" if val > 0 else "" if val == 0 else "-"
                return f"{sign}€{abs(val):,.2f}" if val != 0 else "€0.00"

            def fmt_pct(val):
                sign = "+" if val > 0 else "" if val == 0 else "-"
                return f"{sign}{abs(val):.2f}%" if val != 0 else "0.00%"

            def parse_amount(value):
                if value is None:
                    return 0.0
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, dict):
                    for key in ("amount", "value", "val"):
                        if key in value:
                            return parse_amount(value[key])
                    return 0.0
                if isinstance(value, str):
                    cleaned = "".join(ch for ch in value if ch.isdigit() or ch in ",.-")
                    if cleaned.count(",") > 0 and cleaned.count(".") == 0:
                        cleaned = cleaned.replace(",", ".")
                    try:
                        return float(cleaned)
                    except Exception:
                        return 0.0
                return 0.0

            def lower_text(txn, key):
                return str(txn.get(key, "")).strip().lower()

            dividends = 0.0
            interest = 0.0
            fees = 0.0
            taxes = 0.0
            realized = 0.0

            for txn in transactions:
                title = lower_text(txn, "title")
                subtitle = lower_text(txn, "subtitle")
                amount = parse_amount(txn.get("amount"))
                if "dividende" in subtitle or "dividend" in subtitle or "dividende" in title or "dividend" in title:
                    dividends += amount
                if "zinsen" in title or "interest" in title:
                    interest += amount
                if "gebühr" in title or "fee" in title or "gebühr" in subtitle or "fee" in subtitle:
                    fees += abs(amount)
                if "steuer" in title or "tax" in title or "steuer" in subtitle or "tax" in subtitle:
                    taxes += abs(amount)
                if "verkauf" in title or "sell" in title:
                    realized += amount

            net_sum = profit + dividends + interest + realized - fees - taxes

            rendite_rows = html.Div([
                html.Div([
                    html.Div("Portfoliowert", className="text-muted small"),
                    html.Div(f"€{total_value:,.2f}", className="fw-semibold"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div("Investiert", className="text-muted small"),
                    html.Div(f"€{invested:,.2f}", className="fw-semibold"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div("Cashflow", className="text-muted small"),
                    html.Div(f"€{cash:,.2f}", className="fw-semibold"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div("Kursgewinne", className="text-muted small"),
                    html.Div(f"{fmt_eur(profit)} ({fmt_pct(profit_pct)})", className="fw-semibold text-success" if profit >= 0 else "fw-semibold text-danger"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div("Dividenden (Brutto)", className="text-muted small"),
                    html.Div(fmt_eur(dividends), className="fw-semibold text-success" if dividends >= 0 else "fw-semibold text-danger"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div("Zinsen (Brutto)", className="text-muted small"),
                    html.Div(fmt_eur(interest), className="fw-semibold text-success" if interest >= 0 else "fw-semibold text-danger"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div("Gebühren", className="text-muted small"),
                    html.Div(f"-€{fees:,.2f}" if fees else "€0.00", className="fw-semibold text-danger" if fees else "fw-semibold"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div("Steuern", className="text-muted small"),
                    html.Div(f"-€{taxes:,.2f}" if taxes else "€0.00", className="fw-semibold text-danger" if taxes else "fw-semibold"),
                ], className="d-flex justify-content-between mb-2"),
                html.Hr(className="my-2"),
                html.Div([
                    html.Div("Netto Summe", className="text-muted small"),
                    html.Div(fmt_eur(net_sum), className="fw-semibold text-success" if net_sum >= 0 else "fw-semibold text-danger"),
                ], className="d-flex justify-content-between"),
            ])

            # Recent activities
            def parse_timestamp(ts):
                if not ts:
                    return None
                try:
                    return datetime.fromisoformat(str(ts).replace("+0000", "+00:00")).replace(tzinfo=None)
                except Exception:
                    return None

            recent_items = []
            for txn in sorted(transactions, key=lambda x: x.get("timestamp", ""), reverse=True)[:6]:
                title = txn.get("title") or txn.get("subtitle") or "Aktivität"
                subtitle = txn.get("subtitle") or ""
                amount = parse_amount(txn.get("amount"))
                ts = parse_timestamp(txn.get("timestamp"))
                date_str = ts.strftime("%d.%m.%Y %H:%M") if ts else ""
                amount_str = fmt_eur(amount) if amount else ""
                badge_color = "primary"
                if "kauf" in str(subtitle).lower() or "buy" in str(title).lower():
                    badge_color = "info"
                elif "verkauf" in str(subtitle).lower() or "sell" in str(title).lower():
                    badge_color = "warning"
                elif "einzahlung" in str(title).lower() or "deposit" in str(title).lower():
                    badge_color = "success"
                elif "auszahlung" in str(title).lower() or "withdraw" in str(title).lower():
                    badge_color = "danger"

                recent_items.append(
                    html.Div([
                        html.Div([
                            html.Div(title, className="fw-medium small"),
                            html.Div(date_str, className="text-muted small"),
                        ]),
                        html.Div([
                            dbc.Badge(subtitle or " ", color=badge_color, className="me-2"),
                            html.Div(amount_str, className="small fw-semibold text-end"),
                        ], className="d-flex align-items-center"),
                    ], className="d-flex justify-content-between align-items-center py-2 border-bottom")
                )

            recent_list = html.Div(recent_items) if recent_items else html.Div("No recent activity", className="text-muted text-center py-3")

            # Top movers
            movers = []
            for pos in positions:
                value = float(pos.get("value", 0))
                invested_pos = float(pos.get("invested", 0))
                profit_pos = float(pos.get("profit", value - invested_pos))
                profit_pct_pos = (profit_pos / invested_pos * 100) if invested_pos > 0 else 0
                movers.append({
                    "name": pos.get("name", "Unknown"),
                    "value": value,
                    "profit": profit_pos,
                    "profit_pct": profit_pct_pos,
                })
            movers = sorted(movers, key=lambda x: x.get("profit_pct", 0), reverse=True)[:6]

            mover_items = []
            for m in movers:
                profit_cls = "text-success" if m["profit_pct"] >= 0 else "text-danger"
                mover_items.append(
                    html.Div([
                        html.Div([
                            html.Div(m["name"], className="fw-medium small"),
                            html.Div(f"€{m['value']:,.2f}", className="text-muted small"),
                        ]),
                        html.Div([
                            html.Div(f"{fmt_pct(m['profit_pct'])}", className=f"small fw-semibold {profit_cls}"),
                            html.Div(fmt_eur(m["profit"]), className=f"small {profit_cls}"),
                        ], className="text-end"),
                    ], className="d-flex justify-content-between align-items-center py-2 border-bottom")
                )

            movers_list = html.Div(mover_items) if mover_items else html.Div("No movers", className="text-muted text-center py-3")

            # Securities table
            table_rows = []
            for pos in positions:
                value = float(pos.get("value", 0))
                invested_pos = float(pos.get("invested", 0))
                profit_pos = float(pos.get("profit", value - invested_pos))
                profit_pct_pos = (profit_pos / invested_pos * 100) if invested_pos > 0 else 0
                allocation = (value / total_value * 100) if total_value > 0 else 0
                table_rows.append({
                    "name": pos.get("name", "Unknown"),
                    "value": f"€{value:,.2f}",
                    "profit": f"{fmt_eur(profit_pos)} ({fmt_pct(profit_pct_pos)})",
                    "dividends": "--",
                    "realized": "--",
                    "allocation": f"{allocation:.2f}%",
                })

            securities_table = dash_table.DataTable(
                data=table_rows,
                columns=[
                    {"name": "Name", "id": "name"},
                    {"name": "Position", "id": "value"},
                    {"name": "Kursgewinn", "id": "profit"},
                    {"name": "Dividenden", "id": "dividends"},
                    {"name": "Realisiert", "id": "realized"},
                    {"name": "Allocation", "id": "allocation"},
                ],
                style_cell={"textAlign": "left", "padding": "8px 12px", "fontFamily": "Inter, sans-serif", "fontSize": "12px", "border": "none"},
                style_header={"fontWeight": "600", "backgroundColor": "#f8fafc", "borderBottom": "1px solid #e5e7eb"},
                style_data={"borderBottom": "1px solid #f3f4f6"},
                style_data_conditional=[
                    {"if": {"column_id": "profit", "filter_query": "{profit} contains '+'"}, "color": "#10b981"},
                    {"if": {"column_id": "profit", "filter_query": "{profit} contains '-'"}, "color": "#ef4444"},
                ],
                style_as_list_view=True,
            )

            return rendite_rows, recent_list, movers_list, securities_table

        except Exception:
            return (
                html.Div("No data synced", className="text-muted text-center py-3"),
                html.Div("No recent activity", className="text-muted text-center py-3"),
                html.Div("No movers", className="text-muted text-center py-3"),
                html.Div("No securities", className="text-muted text-center py-3"),
            )
    
    # Global timeframe selection
    @app.callback(
        Output("selected-range", "data"),
        Input("global-timeframe", "value"),
        prevent_initial_call=False
    )
    def update_range(selected_range):
        return selected_range or "max"
    
    def build_portfolio_chart(data_json, chart_type, selected_range, benchmarks, pathname, include_benchmarks):
        # Only render chart on /compare page
        if not pathname or pathname != "/compare":
            return go.Figure()  # Return empty figure instead of raising exception

        fig = go.Figure()
        selected_range = selected_range or "max"
        benchmarks = benchmarks or []
        cache_key = None
        
        if not data_json:
            fig.update_layout(
                height=320,
                margin=dict(l=40, r=20, t=20, b=40),
                plot_bgcolor="white",
                paper_bgcolor="white",
                annotations=[{
                    "text": "Connect to Trade Republic to see your portfolio",
                    "xref": "paper", "yref": "paper",
                    "x": 0.5, "y": 0.5, "showarrow": False,
                    "font": {"size": 14, "color": "#9ca3af"}
                }],
                xaxis=dict(showgrid=False, showticklabels=False),
                yaxis=dict(showgrid=False, showticklabels=False),
            )
            return fig
        
        try:
            data = json.loads(data_json)

            cached_at = data.get("cached_at") or ""
            cache_key = "|".join([
                str(cached_at),
                str(chart_type),
                str(selected_range),
                "1" if include_benchmarks else "0",
                ",".join(map(str, benchmarks)),
            ])

            cached_fig = _fig_cache_get(cache_key)
            if cached_fig is not None:
                return go.Figure(cached_fig)

            # Ensure Plotly does not keep an old zoom/range when data changes.
            # Use stable uirevision so reload doesn't force redraw spam.
            fig.update_layout(uirevision=cache_key)

            history = data.get("data", {}).get("history", [])
            transactions = data.get("data", {}).get("transactions", [])
            
            if not history:
                fig.update_layout(
                    height=320,
                    margin=dict(l=40, r=20, t=20, b=40),
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                    annotations=[{
                        "text": "Historical chart not available from Trade Republic",
                        "xref": "paper", "yref": "paper",
                        "x": 0.5, "y": 0.5, "showarrow": False,
                        "font": {"size": 14, "color": "#9ca3af"}
                    }],
                    xaxis=dict(showgrid=False, showticklabels=False),
                    yaxis=dict(showgrid=False, showticklabels=False),
                )
                return fig
            
            df = pd.DataFrame(history)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # Filter by range
            # Use portfolio history's last date for stable ranges (not wall-clock now)
            end_date = df['date'].max().to_pydatetime()
            if selected_range == "1m":
                start_date = end_date - timedelta(days=30)
            elif selected_range == "3m":
                start_date = end_date - timedelta(days=90)
            elif selected_range == "6m":
                start_date = end_date - timedelta(days=180)
            elif selected_range == "ytd":
                start_date = datetime(end_date.year, 1, 1)
            elif selected_range == "1y":
                start_date = end_date - timedelta(days=365)
            else:
                start_date = df['date'].min()

            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            
            if len(df) == 0:
                fig.update_layout(
                    height=320,
                    margin=dict(l=40, r=20, t=20, b=40),
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                    annotations=[{
                        "text": "No history data for selected range",
                        "xref": "paper", "yref": "paper",
                        "x": 0.5, "y": 0.5, "showarrow": False,
                        "font": {"size": 14, "color": "#9ca3af"}
                    }],
                    xaxis=dict(showgrid=False, showticklabels=False),
                    yaxis=dict(showgrid=False, showticklabels=False),
                )
                return fig
            
            # Calculate based on chart type
            # Now we have real portfolio values from market price calculations

            def _series_to_number_list(series):
                # Convert pandas/numpy series to JSON-friendly python floats.
                # Replace NaN/inf with None so Plotly can handle gaps.
                vals = []
                for v in series.tolist() if hasattr(series, "tolist") else list(series):
                    try:
                        if v is None:
                            vals.append(None)
                            continue
                        fv = float(v)
                        if not math.isfinite(fv):
                            vals.append(None)
                        else:
                            vals.append(fv)
                    except Exception:
                        vals.append(None)
                return vals

            # Use ISO date strings to keep JSON simple and avoid dtype encodings
            x_dates = df['date'].dt.strftime('%Y-%m-%d').tolist()
            
            # Get actual portfolio data
            portfolio = data.get("data", {})
            total_invested = portfolio.get("investedAmount", df['invested'].iloc[-1] if 'invested' in df.columns else df['value'].iloc[-1])
            current_total = portfolio.get("totalValue", df['value'].iloc[-1])
            
            if chart_type == "tab-value":
                # Absolute portfolio value over time
                y_data = df['value']
                y_title = "Portfolio Value (€)"
                y_prefix = "€"
                fill_color = "rgba(99, 102, 241, 0.1)"
            elif chart_type == "tab-performance":
                # Return vs invested at that time (matches benchmark simulation semantics)
                invested_series = df['invested'] if 'invested' in df.columns else None
                if invested_series is not None:
                    y_data = (df['value'] / invested_series.replace(0, pd.NA) - 1) * 100
                else:
                    first_val = df['value'].iloc[0]
                    y_data = (df['value'] / first_val - 1) * 100
                y_title = "Return (%)"
                y_prefix = ""
                fill_color = None
            else:  # drawdown
                # Drawdown from peak portfolio value
                rolling_max = df['value'].expanding().max().replace(0, pd.NA)
                y_data = (df['value'] - rolling_max) / rolling_max * 100
                if 'invested' in df.columns:
                    y_data = y_data.where(df['invested'].replace(0, pd.NA).notna())
                y_title = "Drawdown (%)"
                y_prefix = ""
                fill_color = "rgba(239, 68, 68, 0.2)"
            
            # Portfolio line
            if chart_type == "tab-value":
                portfolio_hover = "<b>Portfolio</b><br>%{x|%d %b %Y}<br>€%{y:,.2f}<extra></extra>"
            else:
                portfolio_hover = "<b>Portfolio</b><br>%{x|%d %b %Y}<br>%{y:,.2f}%<extra></extra>"

            fig.add_trace(go.Scatter(
                x=x_dates,
                y=_series_to_number_list(y_data),
                mode='lines',
                name='Portfolio',
                line=dict(color='#6366f1', width=2),
                fill='tozeroy' if fill_color else None,
                fillcolor=fill_color,
                hovertemplate=portfolio_hover,
            ))
            
            if include_benchmarks and chart_type in ["tab-performance", "tab-value"]:
                # Add benchmarks (value + performance)
                benchmark_colors = {
                    "^GSPC": "#10b981",
                    "^GDAXI": "#f59e0b",
                    "URTH": "#3b82f6",
                    "^IXIC": "#8b5cf6",
                    "^STOXX": "#06b6d4",
                }
                benchmark_names = {
                    "^GSPC": "S&P 500",
                    "^GDAXI": "DAX",
                    "URTH": "MSCI World",
                    "^IXIC": "NASDAQ",
                    "^STOXX": "STOXX 600",
                }

                bench_simulations = {}
                if benchmarks and transactions:
                    try:
                        from components.benchmark_data import get_benchmark_simulation
                        bench_simulations = get_benchmark_simulation(history, transactions, symbols=benchmarks)
                    except Exception:
                        bench_simulations = {}

                for bench in (benchmarks or []):
                    sim_data = bench_simulations.get(bench)
                    if sim_data:
                        sim_df = pd.DataFrame(sim_data)
                        sim_df['date'] = pd.to_datetime(sim_df['date'])

                        # Filter to same date range
                        sim_df = sim_df[(sim_df['date'] >= pd.Timestamp(start_date)) & (sim_df['date'] <= pd.Timestamp(end_date))]
                        if len(sim_df) == 0:
                            continue

                        if chart_type == "tab-performance":
                            bench_y = (sim_df['value'] / sim_df['invested'].replace(0, pd.NA) - 1) * 100
                            hovertemplate = f"<b>{benchmark_names.get(bench, bench)}</b><br>%{{x|%d %b %Y}}<br>%{{y:,.2f}}%<extra></extra>"
                        else:
                            bench_y = sim_df['value']
                            hovertemplate = f"<b>{benchmark_names.get(bench, bench)}</b><br>%{{x|%d %b %Y}}<br>€%{{y:,.2f}}<extra></extra>"

                        fig.add_trace(go.Scatter(
                            x=sim_df['date'].dt.strftime('%Y-%m-%d').tolist(),
                            y=_series_to_number_list(bench_y),
                            mode='lines',
                            name=benchmark_names.get(bench, bench),
                            line=dict(color=benchmark_colors.get(bench, "#888"), width=1.5, dash='dot'),
                            hovertemplate=hovertemplate,
                        ))
                    else:
                        # Fallback: if simulation isn't available, use normalized index data.
                        bench_data = fetch_benchmark_data(
                            bench,
                            start_date.strftime("%Y-%m-%d"),
                            end_date.strftime("%Y-%m-%d"),
                        )
                        if bench_data is None or len(bench_data) == 0:
                            continue

                        first_bench = bench_data['Close'].iloc[0]
                        if chart_type == "tab-performance":
                            bench_y = (bench_data['Close'] / first_bench - 1) * 100
                        else:
                            first_port = df['invested'].iloc[0] if 'invested' in df.columns else df['value'].iloc[0]
                            bench_y = bench_data['Close'] / first_bench * first_port

                        fig.add_trace(go.Scatter(
                            x=pd.to_datetime(bench_data['Date']).dt.strftime('%Y-%m-%d').tolist(),
                            y=_series_to_number_list(bench_y),
                            mode='lines',
                            name=benchmark_names.get(bench, bench),
                            line=dict(color=benchmark_colors.get(bench, "#888"), width=1.5, dash='dot'),
                        ))
            
            fig.update_layout(
                height=320,
                margin=dict(l=40, r=20, t=20, b=40),
                plot_bgcolor="white",
                paper_bgcolor="white",
                font=dict(family="Inter, sans-serif", size=11),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                xaxis=dict(
                    showgrid=True, 
                    gridcolor="#f3f4f6", 
                    tickformat="%b %Y" if selected_range in ["max", "1y"] else "%d %b"
                ),
                yaxis=dict(
                    showgrid=True, 
                    gridcolor="#f3f4f6", 
                    title=y_title,
                    tickprefix=y_prefix if chart_type == "tab-value" else "",
                    ticksuffix="%" if chart_type != "tab-value" else "",
                ),
                hovermode="x unified",
            )

            # Cache successful figure builds so reloads are instant.
            if cache_key:
                _fig_cache_set(cache_key, fig.to_dict())

            # Optional debug snapshot (disabled by default to avoid disk I/O).
            if _DEBUG_WRITE_COMPARE_SUMMARY:
                try:
                    from components.benchmark_data import CACHE_DIR
                    created_at = datetime.now().isoformat()
                    summary_payload = {
                        "created_at": created_at,
                        "chart_type": chart_type,
                        "selected_range": selected_range,
                        "benchmarks": benchmarks,
                        "data_source": "portfolio_data_store",
                        "history_points": int(len(history) if history else 0),
                        "filtered_points": int(len(df)),
                    }
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    (CACHE_DIR / "last_compare_summary.json").write_text(
                        json.dumps(summary_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

            return fig
            
        except Exception as e:
            # Avoid noisy prints; return empty figure.
            return fig



    # Main chart (Value / Drawdown)
    @app.callback(
        Output("main-portfolio-chart-v2", "figure"),
        [Input("portfolio-data-store", "data"),
         Input("chart-tabs", "active_tab"),
         Input("selected-range", "data"),
         Input("benchmark-selector", "value")],
        State("url", "pathname"),
        prevent_initial_call=False
    )
    def update_chart(data_json, chart_type, selected_range, benchmarks, pathname):
        return build_portfolio_chart(
            data_json,
            chart_type,
            selected_range,
            benchmarks,
            pathname,
            include_benchmarks=True,
        )

    # Performance chart (benchmarks only here)
    @app.callback(
        Output("performance-chart", "figure"),
        [Input("portfolio-data-store", "data"),
         Input("selected-range", "data"),
         Input("benchmark-selector", "value")],
        State("url", "pathname"),
        prevent_initial_call=False
    )
    def update_performance_chart(data_json, selected_range, benchmarks, pathname):
        return build_portfolio_chart(
            data_json,
            "tab-performance",
            selected_range,
            benchmarks,
            pathname,
            include_benchmarks=True,
        )

    # Privacy mode toggle (clientside so it reacts instantly)
    app.clientside_callback(
        """
        function(n_clicks, is_private) {
            const current = Boolean(is_private);
            const next = n_clicks ? !current : current;

            const icon = next
                ? {type: 'I', namespace: 'dash_html_components', props: {className: 'bi bi-eye me-2'}}
                : {type: 'I', namespace: 'dash_html_components', props: {className: 'bi bi-eye-slash me-2'}};

            const label = next ? 'Show Values' : 'Hide Values';
            const cls = next ? 'portfolio-analysis-page privacy-on' : 'portfolio-analysis-page';

            return [next, [icon, label], cls];
        }
        """,
        [Output("privacy-mode", "data"),
         Output("toggle-privacy-btn", "children"),
         Output("portfolio-analysis-root", "className")],
        Input("toggle-privacy-btn", "n_clicks"),
        State("privacy-mode", "data"),
        prevent_initial_call=False,
    )
    
    # Comparison table
    @app.callback(
        Output("comparison-table-container", "children"),
        [Input("portfolio-data-store", "data"),
         Input("benchmark-selector", "value")],
        State("url", "pathname"),
        prevent_initial_call=False
    )
    def update_comparison_table(data_json, benchmarks, pathname):
        if not pathname or pathname != "/compare":
            return html.Div()
        if not data_json:
            return html.Div("No data available", className="text-muted text-center py-3")
        
        try:
            data = json.loads(data_json)
            history = data.get("data", {}).get("history", [])
            portfolio = data.get("data", {})
            
            if not history:
                return html.Div("No history data", className="text-muted text-center py-3")
            
            df = pd.DataFrame(history)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # Current portfolio value
            current_value = df['value'].iloc[-1]
            
            # Calculate returns based on actual portfolio values
            def calc_return(days_ago):
                """Calculate return from X days ago to now."""
                target_date = datetime.now() - timedelta(days=days_ago)
                past_data = df[df['date'] <= target_date]
                if len(past_data) == 0:
                    past_data = df.head(1)
                past_value = past_data['value'].iloc[-1]
                if past_value > 0:
                    return (current_value - past_value) / past_value * 100
                return 0
            
            # YTD
            ytd_start = df[df['date'] >= datetime(datetime.now().year, 1, 1)]
            if len(ytd_start) > 0:
                ytd_value = ytd_start['value'].iloc[0]
                ytd_return = (current_value - ytd_value) / ytd_value * 100 if ytd_value > 0 else 0
            else:
                ytd_return = 0
            
            # Total return (from first data point)
            first_value = df['value'].iloc[0]
            total_return = (current_value - first_value) / first_value * 100 if first_value > 0 else 0
            
            rows = [{
                "Asset": "Your Portfolio",
                "1M": f"{calc_return(30):+.1f}%",
                "3M": f"{calc_return(90):+.1f}%",
                "YTD": f"{ytd_return:+.1f}%",
                "1Y": f"{calc_return(365):+.1f}%",
                "Total": f"{total_return:+.1f}%",
            }]
            
            # Add benchmarks
            benchmark_names = {
                "^GSPC": "S&P 500",
                "^GDAXI": "DAX",
                "URTH": "MSCI World",
                "^IXIC": "NASDAQ",
                "^STOXX": "STOXX 600",
            }
            end_date = datetime.now()
            
            for bench in (benchmarks or []):
                bench_data = fetch_benchmark_data(bench, (end_date - timedelta(days=365*3)).strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
                if bench_data is not None and len(bench_data) > 0:
                    bdf = bench_data.copy()
                    bdf['Date'] = pd.to_datetime(bdf['Date'])
                    bdf = bdf.sort_values('Date')
                    
                    current_bench = bdf['Close'].iloc[-1]
                    
                    def bench_return(days_ago):
                        target = end_date - timedelta(days=days_ago)
                        past = bdf[bdf['Date'] <= target]
                        if len(past) == 0:
                            return 0
                        past_val = past['Close'].iloc[-1]
                        return (current_bench - past_val) / past_val * 100 if past_val > 0 else 0
                    
                    # YTD
                    ytd_bench = bdf[bdf['Date'] >= datetime(end_date.year, 1, 1)]
                    ytd_b = 0
                    if len(ytd_bench) > 0:
                        ytd_b = (current_bench - ytd_bench['Close'].iloc[0]) / ytd_bench['Close'].iloc[0] * 100
                    
                    first_bench = bdf['Close'].iloc[0]
                    total_b = (current_bench - first_bench) / first_bench * 100 if first_bench > 0 else 0
                    
                    rows.append({
                        "Asset": benchmark_names.get(bench, bench),
                        "1M": f"{bench_return(30):+.1f}%",
                        "3M": f"{bench_return(90):+.1f}%",
                        "YTD": f"{ytd_b:+.1f}%",
                        "1Y": f"{bench_return(365):+.1f}%",
                        "Total": f"{total_b:+.1f}%",
                    })
            
            table = dash_table.DataTable(
                data=rows,
                columns=[
                    {"name": "Asset", "id": "Asset"},
                    {"name": "1M", "id": "1M"},
                    {"name": "3M", "id": "3M"},
                    {"name": "YTD", "id": "YTD"},
                    {"name": "1Y", "id": "1Y"},
                    {"name": "Total", "id": "Total"},
                ],
                style_cell={"textAlign": "center", "padding": "8px 12px", "fontFamily": "Inter, sans-serif", "fontSize": "12px", "border": "none"},
                style_header={"fontWeight": "600", "backgroundColor": "#f8fafc", "borderBottom": "1px solid #e5e7eb"},
                style_data={"borderBottom": "1px solid #f3f4f6"},
                style_data_conditional=[
                    {"if": {"filter_query": "{1M} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{1M} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{3M} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{3M} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{YTD} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{YTD} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{1Y} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{1Y} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{Total} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{Total} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{Asset} = \"Your Portfolio\""}, "backgroundColor": "#eef2ff", "fontWeight": "500"},
                    {"if": {"column_id": "Asset"}, "textAlign": "left"},
                ],
                style_as_list_view=True,
            )
            
            return table
            
        except Exception as e:
            print(f"Error creating table: {e}")
            return html.Div(f"Error: {str(e)}", className="text-danger text-center py-3")
