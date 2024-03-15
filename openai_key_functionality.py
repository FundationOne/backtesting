import dash_bootstrap_components as dbc
from dash import dcc, no_update
from dash.dependencies import Input, Output, State

# OpenAI API key input
openai_api_key_input = dbc.Row([
    dcc.Store(id='api_key_store', storage_type='session'),  # Stores the API key in the session storage
    dbc.Label("OpenAI API Key", html_for="input-openai-api-key", width=12),
    dbc.Col([
        dcc.Input(id="input-openai-api-key", type="text", placeholder="Enter your OpenAI API key")
    ], width=12)
])


def register_callbacks(app):
    @app.callback(
        Output('api_key_store', 'data'),
        [Input("input-openai-api-key", "value")],
        prevent_initial_call=True
    )
    def update_cached_api_key(new_api_key):
        if new_api_key:
            return {'api_key': new_api_key}  # Update session storage
        return no_update
    
    @app.callback(
        Output('input-openai-api-key', 'value'),
        Input('label-for-api-key', 'children'),  # Using the label as a trigger
        State('api_key_store', 'data')
    )
    def initialize_api_key_input(_trigger, data):
        if data and 'api_key' in data:
            return data['api_key']
        # Return an empty string to ensure the callback doesn't fail if no data is found
        return ''