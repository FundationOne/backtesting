"""APE•X - Portfolio & Backtesting Application"""
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output

# Page imports
from pages.backtesting_sim import layout as l1, register_callbacks as rc1
from pages.portfolio_sim import layout as l2, register_callbacks as rc2
from pages.riskbands import layout as l3, register_callbacks as rc3
from pages.portfolio_analysis import layout as l4, register_callbacks as rc4

# Component imports
from components.settings_modal import (
    settings_button, settings_modal, api_key_store, 
    register_settings_callbacks
)
from components.rule_builder import register_rule_builder_callbacks
from components.auth import login_modal, user_store, register_auth_callbacks

print("STARTING APP")

# Initialize app with modern Bootstrap and icons
app = dash.Dash(
    __name__, 
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
        html.P("Portfolio & Backtesting", className="sidebar-tagline"),
    ], className="sidebar-brand"),
    
    html.Hr(className="sidebar-divider"),
    
    # Navigation
    dbc.Nav([
        dbc.NavLink([
            html.I(className="bi bi-graph-up me-2"), 
            "Backtesting"
        ], href="/backtesting", id="backtesting-link", className="nav-link-modern"),
        
        dbc.NavLink([
            html.I(className="bi bi-wallet2 me-2"), 
            "Investment Simulator"
        ], href="/portfolio", id="portfolio-link", className="nav-link-modern"),
        
        dbc.NavLink([
            html.I(className="bi bi-bar-chart-line me-2"), 
            "Portfolio Analysis"
        ], href="/compare", id="compare-link", className="nav-link-modern"),
        
        dbc.NavLink([
            html.I(className="bi bi-shield-check me-2"), 
            "Exit Strategy Riskbands"
        ], href="/riskbands", id="riskbands-link", className="nav-link-modern"),
    ], vertical=True, pills=True, className="sidebar-nav"),
    
    # Bottom section with settings + user
    html.Div([
        settings_button,
        html.Div([
            html.Div(id="current-user-label", className="small text-muted mb-1"),
            dbc.Button(
                [html.I(className="bi bi-box-arrow-right me-1"), "Logout"],
                id="logout-btn",
                color="secondary",
                outline=True,
                size="sm",
                className="w-100"
            ),
        ], className="mt-2")
    ], className='sidebar-bottom'),
], className='sidebar')

# Main content area
content = html.Div(id="page-content", className='main-content')

# App layout
app.layout = dbc.Container([
    dcc.Location(id="url", refresh=False),
    api_key_store,
    user_store,  # User auth store
    dcc.Store(id="portfolio-data-store", storage_type="session"),  # Portfolio data - avoid stale localStorage
    dcc.Store(id="tr-encrypted-creds", storage_type="local"),  # TR credentials - MUST be in main layout for auth
    login_modal,  # Login gate
    settings_modal,
    dbc.Row([
        dbc.Col(sidebar, width=2, className='p-0 sidebar-col'),
        dbc.Col(content, width=10, className='p-0'),
    ], className='g-0')
], fluid=True, className='app-container p-0')

# Navigation callbacks
@app.callback(
    Output('url', 'pathname'),
    [Input('url', 'pathname')]
)
def redirect_to_default(pathname):
    if pathname == "/" or pathname is None:
        return "/backtesting"
    return dash.no_update


@app.callback(
    Output('page-content', 'children'),
    [Input('url', 'pathname')]
)
def render_page_content(pathname):
    if pathname == "/backtesting":
        return l1
    elif pathname == "/portfolio":
        return l2
    elif pathname == "/compare":
        return l4
    elif pathname == "/riskbands":
        return l3
    else:
        return html.Div([
            html.H3("404 - Page Not Found", className="text-center mt-5"),
            html.P("The page you're looking for doesn't exist.", className="text-center text-muted"),
        ])


@app.callback(
    [Output("backtesting-link", "active"),
     Output("portfolio-link", "active"),
     Output("compare-link", "active"),
     Output("riskbands-link", "active")],
    [Input("url", "pathname")]
)
def set_active_link(pathname):
    return (
        pathname == "/backtesting",
        pathname == "/portfolio",
        pathname == "/compare",
        pathname == "/riskbands",
    )


# Register all callbacks
register_auth_callbacks(app)  # Auth first
register_settings_callbacks(app)
register_rule_builder_callbacks(app)
rc4(app)  # Portfolio comparison callbacks
rc3(app)  # Riskbands callbacks
rc2(app)  # Portfolio simulation callbacks
rc1(app)  # Backtesting callbacks

# Run
if __name__ == '__main__':
    app.run_server(debug=True, port=8888, use_reloader=False)
