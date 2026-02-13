"""Settings modal component with cog icon trigger."""
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, no_update

# Settings button (cog icon) for the sidebar
settings_button = html.Div(
    dbc.Button(
        html.I(className="bi bi-gear-fill"),
        id="open-settings-modal",
        className="settings-btn",
        color="link",
        n_clicks=0,
    ),
    className="settings-trigger"
)

# Settings modal
settings_modal = dbc.Modal(
    [
        dbc.ModalHeader(
            dbc.ModalTitle([
                html.I(className="bi bi-gear me-2"),
                "Settings"
            ]),
            close_button=True
        ),
        dbc.ModalBody([
            # OpenAI API Key Section
            html.Div([
                html.Label("OpenAI API Key", className="settings-label"),
                html.P("Required for AI-powered rule generation", className="settings-help"),
                dbc.Input(
                    id="input-openai-api-key",
                    type="password",
                    placeholder="sk-...",
                    className="settings-input"
                ),
            ], className="settings-section"),
            
            html.Hr(className="settings-divider"),
            
            # Chart Scale Section
            html.Div([
                html.Label("Chart Scale", className="settings-label"),
                html.P("Select how values are displayed on charts", className="settings-help"),
                dbc.RadioItems(
                    options=[
                        {"label": "Logarithmic", "value": "log"},
                        {"label": "Linear", "value": "linear"},
                    ],
                    value="linear",
                    id="scale-toggle",
                    className="settings-radio",
                    inline=True
                ),
            ], className="settings-section"),
            
            html.Hr(className="settings-divider"),
            
            # Theme Section (future)
            html.Div([
                html.Label("Display Theme", className="settings-label"),
                html.P("Choose your preferred color scheme", className="settings-help"),
                dbc.RadioItems(
                    options=[
                        {"label": "Light", "value": "light"},
                        {"label": "Dark", "value": "dark"},
                    ],
                    value="light",
                    id="theme-toggle",
                    className="settings-radio",
                    inline=True,
                    # disabled=True  # Future feature
                ),
            ], className="settings-section"),

            html.Hr(className="settings-divider"),

            # GoCardless Bank Account Data Section
            html.Div([
                html.Label("GoCardless Bank Sync", className="settings-label"),
                html.P([
                    "Credentials for bank account sync (",
                    html.A("Get free key", href="https://bankaccountdata.gocardless.com/signup",
                           target="_blank", className="small"),
                    ")",
                ], className="settings-help"),
                dbc.Input(
                    id="settings-gc-secret-id",
                    type="password",
                    placeholder="Secret ID",
                    className="settings-input mb-2",
                    size="sm",
                ),
                dbc.Input(
                    id="settings-gc-secret-key",
                    type="password",
                    placeholder="Secret Key",
                    className="settings-input",
                    size="sm",
                ),
                html.Div(id="settings-gc-feedback", className="mt-1"),
            ], className="settings-section"),
        ]),
        dbc.ModalFooter(
            dbc.Button("Done", id="close-settings-modal", className="btn-primary", n_clicks=0)
        ),
    ],
    id="settings-modal",
    is_open=False,
    centered=True,
    size="md",
)

# Hidden store for API key persistence
api_key_store = dcc.Store(id='api_key_store', storage_type='session')


def register_settings_callbacks(app):
    """Register callbacks for the settings modal."""
    
    @app.callback(
        Output("settings-modal", "is_open"),
        [Input("open-settings-modal", "n_clicks"),
         Input("close-settings-modal", "n_clicks")],
        [State("settings-modal", "is_open")],
        prevent_initial_call=True
    )
    def toggle_settings_modal(open_clicks, close_clicks, is_open):
        if open_clicks or close_clicks:
            return not is_open
        return is_open
    
    @app.callback(
        Output('api_key_store', 'data'),
        [Input("input-openai-api-key", "value")],
        prevent_initial_call=True
    )
    def update_cached_api_key(new_api_key):
        if new_api_key:
            return {'api_key': new_api_key}
        return no_update
    
    @app.callback(
        Output('input-openai-api-key', 'value'),
        Input('url', 'pathname'),
        State('api_key_store', 'data')
    )
    def initialize_api_key_input(_trigger, data):
        if data and 'api_key' in data:
            return data['api_key']
        return ''

    # GoCardless credentials — save when both fields filled
    @app.callback(
        Output('settings-gc-feedback', 'children'),
        [Input('settings-gc-secret-id', 'value'),
         Input('settings-gc-secret-key', 'value')],
        prevent_initial_call=True
    )
    def save_gc_from_settings(sid, skey):
        if sid and skey:
            try:
                from components.gocardless_api import save_credentials
                save_credentials(sid, skey)
                return html.Span("Saved ✓", className="text-success small")
            except Exception:
                return html.Span("Save failed", className="text-danger small")
        return ""

    # Populate GC fields on page load
    @app.callback(
        [Output('settings-gc-secret-id', 'value'),
         Output('settings-gc-secret-key', 'value')],
        Input('url', 'pathname'),
    )
    def init_gc_fields(_pathname):
        try:
            from components.gocardless_api import get_credentials
            sid, skey = get_credentials()
            return sid or '', skey or ''
        except Exception:
            return '', ''
