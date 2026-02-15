"""APE•X - Portfolio & Backtesting Application"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State

# Page imports
from pages.backtesting_sim import layout as l1, register_callbacks as rc1
from pages.portfolio_sim import layout as l2, register_callbacks as rc2
from pages.riskbands import layout as l3, register_callbacks as rc3
from pages.portfolio_analysis import layout as l4, register_callbacks as rc4
from pages.the_real_cost import layout as l5, register_callbacks as rc5
from pages.bank_sync import layout as l6, register_callbacks as rc6

# Component imports
from components.settings_modal import (
    settings_button, settings_modal, api_key_store, 
    register_settings_callbacks
)
from components.rule_builder import register_rule_builder_callbacks
from components.auth import login_modal, user_store, register_auth_callbacks
from components.i18n import t, get_lang

print("STARTING APP")

# Initialize app with modern Bootstrap and icons
app = dash.Dash(
    __name__, 
    title="Apex",
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
    ], 
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)

# Sidebar with modern styling
sidebar = html.Div([
    # Logo section
    html.Div([
        html.H2('APE•X', className='sidebar-logo'),
        html.P("Portfolio & Backtesting", id="sidebar-tagline", className="sidebar-tagline"),
    ], className="sidebar-brand"),
    
    html.Hr(className="sidebar-divider"),
    
    # Navigation
    dbc.Nav([
        dbc.NavLink([
            html.I(className="bi bi-bar-chart-line me-2"), 
            html.Span("Portfolio Analysis", id="nav-text-compare"),
        ], href="/compare", id="compare-link", className="nav-link-modern"),
        
        dbc.NavLink([
            html.I(className="bi bi-graph-up me-2"), 
            html.Span("Backtesting", id="nav-text-backtesting"),
        ], href="/backtesting", id="backtesting-link", className="nav-link-modern"),
        
        dbc.NavLink([
            html.I(className="bi bi-wallet2 me-2"), 
            html.Span("Investment Simulator", id="nav-text-portfolio"),
        ], href="/portfolio", id="portfolio-link", className="nav-link-modern"),
        
        dbc.NavLink([
            html.I(className="bi bi-bank me-2"), 
            html.Span("Bank Account Sync", id="nav-text-banksync"),
        ], href="/banksync", id="banksync-link", className="nav-link-modern"),

        dbc.NavLink([
            html.I(className="bi bi-shield-check me-2"), 
            html.Span("Exit Strategy Riskbands", id="nav-text-riskbands"),
        ], href="/riskbands", id="riskbands-link", className="nav-link-modern"),

        dbc.NavLink([
            html.I(className="bi bi-currency-dollar me-2"), 
            html.Span("The Real Cost", id="nav-text-realcost"),
        ], href="/realcost", id="realcost-link", className="nav-link-modern"),
    ], vertical=True, pills=True, className="sidebar-nav"),
    
    # Bottom section with settings + language + user
    html.Div([
        html.Div([
            settings_button,
            html.Div([
                dbc.Button(
                    html.Span("🇬🇧", id="lang-flag-icon", style={"fontSize": "1.15rem"}),
                    id="lang-dropdown-toggle",
                    className="settings-btn",
                    color="link",
                    n_clicks=0,
                ),
                html.Div([
                    html.Div([
                        html.Span("🇬🇧", style={"fontSize": "1rem"}),
                        html.Span("English", className="ms-2 small"),
                    ], id="lang-opt-en", className="lang-dropdown-item", n_clicks=0),
                    html.Div([
                        html.Span("🇩🇪", style={"fontSize": "1rem"}),
                        html.Span("Deutsch", className="ms-2 small"),
                    ], id="lang-opt-de", className="lang-dropdown-item", n_clicks=0),
                ], id="lang-dropdown-menu", className="lang-dropdown-menu", style={"display": "none"}),
            ], className="position-relative"),
        ], className="d-flex align-items-center justify-content-center gap-1"),
        html.Div([
            html.Div(id="current-user-label", className="sidebar-user-label"),
            dbc.Button(
                [html.I(className="bi bi-box-arrow-right me-1"), "Logout"],
                id="logout-btn",
                color="secondary",
                outline=True,
                size="sm",
                className="w-100",
                style={"display": "none"},
            ),
            dbc.Button(
                [html.I(className="bi bi-person me-1"), "Login"],
                id="open-login-btn",
                color="primary",
                outline=True,
                size="sm",
                className="w-100",
            ),
        ], className="mt-2")
    ], className='sidebar-bottom'),
], className='sidebar')

# Main content area
content = html.Div(id="page-content", className='main-content')

# Mobile hamburger button (visible only on small screens)
mobile_header = html.Div([
    html.Button(
        html.I(className="bi bi-list", style={"fontSize": "1.5rem"}),
        id="mobile-menu-btn",
        className="mobile-menu-btn",
        n_clicks=0,
    ),
    html.Span("APE•X", className="mobile-header-title"),
], className="mobile-header")

# Mobile overlay (click to close sidebar)
mobile_overlay = html.Div(id="mobile-overlay", className="mobile-overlay", n_clicks=0)

# App layout
app.layout = dbc.Container([
    dcc.Location(id="url", refresh=False),
    api_key_store,
    user_store,  # User auth store
    dcc.Store(id="lang-store", storage_type="local", data="en"),  # Language preference
    html.Button(id="open-settings-link", style={"display": "none"}, n_clicks=0),  # Hidden trigger for settings modal from links
    dcc.Store(id="portfolio-data-store", storage_type="memory"),  # Portfolio data - memory only, no persistence
    dcc.Store(id="tr-encrypted-creds", storage_type="local"),  # TR credentials - MUST be in main layout for auth
    dcc.Store(id="demo-mode", data=True, storage_type="local"),  # Demo mode flag - must be in main layout for auth callbacks

    dcc.Interval(id="load-cached-data-interval", interval=500, max_intervals=1),  # Initial data load trigger
    login_modal,  # Login gate
    settings_modal,
    mobile_header,
    mobile_overlay,
    dcc.Store(id="mobile-sidebar-dummy"),
    dbc.Row([
        dbc.Col(sidebar, width=2, className='p-0 sidebar-col'),
        dbc.Col(content, width=10, className='p-0'),
    ], className='g-0')
], fluid=True, className='app-container p-0')

# Provide a superset layout for callback validation in multi-page mode.
# This avoids "nonexistent object" errors for page-scoped component IDs.
app.validation_layout = html.Div([
    app.layout,
    l1("en"),
    l2("en"),
    l3("en"),
    l4("en"),
    l5("en"),
    l6("en"),
])

# Navigation callbacks
@app.callback(
    Output('url', 'pathname'),
    [Input('url', 'pathname')]
)
def redirect_to_default(pathname):
    if pathname == "/" or pathname is None:
        return "/compare"
    return dash.no_update


@app.callback(
    Output('page-content', 'children'),
    [Input('url', 'pathname'),
     Input('lang-store', 'data')],
)
def render_page_content(pathname, lang_data):
    lang = get_lang(lang_data)
    if pathname == "/compare":
        return l4(lang)
    elif pathname == "/backtesting":
        return l1(lang)
    elif pathname == "/portfolio":
        return l2(lang)
    elif pathname == "/banksync":
        return l6(lang)
    elif pathname == "/riskbands":
        return l3(lang)
    elif pathname == "/realcost":
        return l5(lang)
    else:
        return html.Div([
            html.H3(t("nav.404_title", lang), className="text-center mt-5"),
            html.P(t("nav.404_text", lang), className="text-center text-muted"),
        ])


@app.callback(
    [Output("backtesting-link", "active"),
     Output("portfolio-link", "active"),
     Output("compare-link", "active"),
     Output("banksync-link", "active"),
     Output("riskbands-link", "active"),
     Output("realcost-link", "active")],
    [Input("url", "pathname")]
)
def set_active_link(pathname):
    return (
        pathname == "/backtesting",
        pathname == "/portfolio",
        pathname == "/compare",
        pathname == "/banksync",
        pathname == "/riskbands",
        pathname == "/realcost",
    )


# Language dropdown — toggle open/close + select language
app.clientside_callback(
    """
    function(n_toggle, n_en, n_de, current_lang) {
        var triggered = window.dash_clientside.callback_context.triggered;
        if (!triggered || !triggered.length) return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        var id = triggered[0].prop_id.split('.')[0];
        if (id === 'lang-dropdown-toggle') {
            var menu = document.getElementById('lang-dropdown-menu');
            var visible = menu && menu.style.display !== 'none';
            return [{"display": visible ? "none" : "block"}, window.dash_clientside.no_update];
        }
        if (id === 'lang-opt-en') return [{"display": "none"}, "en"];
        if (id === 'lang-opt-de') return [{"display": "none"}, "de"];
        return [window.dash_clientside.no_update, window.dash_clientside.no_update];
    }
    """,
    [Output("lang-dropdown-menu", "style"),
     Output("lang-store", "data")],
    [Input("lang-dropdown-toggle", "n_clicks"),
     Input("lang-opt-en", "n_clicks"),
     Input("lang-opt-de", "n_clicks")],
    State("lang-store", "data"),
    prevent_initial_call=True,
)


# Update language flag icon when language changes
@app.callback(
    Output("lang-flag-icon", "children"),
    Input("lang-store", "data"),
)
def update_lang_flag(lang_data):
    lang = get_lang(lang_data)
    return "🇩🇪" if lang == "de" else "🇬🇧"


# Update sidebar nav labels when language changes
@app.callback(
    [Output("nav-text-compare", "children"),
     Output("nav-text-backtesting", "children"),
     Output("nav-text-portfolio", "children"),
     Output("nav-text-banksync", "children"),
     Output("nav-text-riskbands", "children"),
     Output("nav-text-realcost", "children"),
     Output("sidebar-tagline", "children")],
    Input("lang-store", "data"),
)
def update_sidebar_lang(lang_data):
    lang = get_lang(lang_data)
    return (
        t("nav.portfolio_analysis", lang),
        t("nav.backtesting", lang),
        t("nav.investment_simulator", lang),
        t("nav.bank_sync", lang),
        t("nav.riskbands", lang),
        t("nav.real_cost", lang),
        t("nav.tagline", lang),
    )


# Mobile sidebar toggle (clientside for instant response)
app.clientside_callback(
    """
    function(menu_clicks, overlay_clicks, pathname) {
        const ctx = dash_clientside.callback_context;
        const triggered = (ctx && ctx.triggered && ctx.triggered.length)
            ? ctx.triggered[0].prop_id.split(".")[0]
            : null;

        // Close sidebar on navigation or overlay click
        if (triggered === "mobile-overlay" || triggered === "url") {
            document.body.classList.remove("sidebar-open");
            return dash_clientside.no_update;
        }

        // Toggle sidebar on hamburger click
        if (triggered === "mobile-menu-btn") {
            document.body.classList.toggle("sidebar-open");
        }
        return dash_clientside.no_update;
    }
    """,
    Output("mobile-sidebar-dummy", "data"),
    [Input("mobile-menu-btn", "n_clicks"),
     Input("mobile-overlay", "n_clicks"),
     Input("url", "pathname")],
    prevent_initial_call=True,
)

# Register all callbacks
register_auth_callbacks(app)  # Auth first
register_settings_callbacks(app)
register_rule_builder_callbacks(app)
rc4(app)  # Portfolio comparison callbacks
rc3(app)  # Riskbands callbacks
rc2(app)  # Portfolio simulation callbacks
rc1(app)  # Backtesting callbacks
rc5(app)  # The Real Cost callbacks
rc6(app)  # Bank Account Sync callbacks

# Expose WSGI server for gunicorn (gunicorn main:server)
server = app.server

# Run
if __name__ == '__main__':
    debug = os.environ.get("DASH_DEBUG", "1") == "1"
    port = int(os.environ.get("PORT", 8888))
    app.run_server(debug=debug, port=port, use_reloader=debug)
