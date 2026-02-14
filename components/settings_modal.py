"""Settings modal component with cog icon trigger."""
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, no_update, ClientsideFunction

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
            # html.Div([
            #     html.Label("Chart Scale", className="settings-label"),
            #     html.P("Select how values are displayed on charts", className="settings-help"),
            #     dbc.RadioItems(
            #         options=[
            #             {"label": "Logarithmic", "value": "log"},
            #             {"label": "Linear", "value": "linear"},
            #         ],
            #         value="linear",
            #         id="scale-toggle",
            #         className="settings-radio",
            #         inline=True
            #     ),
            # ], className="settings-section"),
            
            # html.Hr(className="settings-divider"),
            
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

# Hidden store for API key persistence (memory — persisted per-user via clientside JS)
api_key_store = html.Div([
    dcc.Store(id='api_key_store', storage_type='memory'),
    html.Div(id="apikey-save-trigger", style={"display": "none"}),
])


def register_settings_callbacks(app):
    """Register callbacks for the settings modal."""
    
    @app.callback(
        Output("settings-modal", "is_open"),
        [Input("open-settings-modal", "n_clicks"),
         Input("close-settings-modal", "n_clicks"),
         Input("open-settings-link", "n_clicks")],
        [State("settings-modal", "is_open")],
        prevent_initial_call=True
    )
    def toggle_settings_modal(open_clicks, close_clicks, link_clicks, is_open):
        if open_clicks or close_clicks or link_clicks:
            return not is_open
        return is_open
    
    @app.callback(
        Output('api_key_store', 'data', allow_duplicate=True),
        [Input("input-openai-api-key", "value")],
        prevent_initial_call=True
    )
    def update_cached_api_key(new_api_key):
        if new_api_key:
            return {'api_key': new_api_key}
        return no_update
    
    @app.callback(
        Output('input-openai-api-key', 'value'),
        Input('api_key_store', 'data'),
    )
    def initialize_api_key_input(data):
        if data and 'api_key' in data:
            return data['api_key']
        return ''

    # ── Per-user persistence: save API key to localStorage on change ──
    app.clientside_callback(
        """
        function(api_data, user) {
            if (!user || !api_data || !api_data.api_key) return "";
            try {
                localStorage.setItem("apex_apikey_" + user, api_data.api_key);
            } catch(e) { console.error("API key save error:", e); }
            return "";
        }
        """,
        Output("apikey-save-trigger", "children"),
        [Input("api_key_store", "data")],
        [State("current-user-store", "data")],
        prevent_initial_call=True,
    )

    # ── Per-user persistence: load API key from localStorage on login / page load ──
    # This is the PRIMARY output (no allow_duplicate) so it fires on initial load.
    app.clientside_callback(
        """
        function(user, pathname) {
            if (!user) return null;
            try {
                var key = localStorage.getItem("apex_apikey_" + user);
                if (key) return {"api_key": key};
            } catch(e) { console.error("API key load error:", e); }
            return null;
        }
        """,
        Output("api_key_store", "data"),
        [Input("current-user-store", "data"),
         Input("url", "pathname")],
    )


