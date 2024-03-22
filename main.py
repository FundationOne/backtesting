import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output

from backtesting_sim import layout as l1, register_callbacks as rc1
from portfolio_sim import layout as l2, register_callbacks as rc2
from gpt_functionality import register_callbacks as rc_gpt
from openai_key_functionality import openai_api_key_input as l_openai_key, register_callbacks as rc_openai_key
from settings_functionality import settings_scale_toggle as l_settings_scale_toggle

print("STARTING APP")

# Choose a theme closer to Apple's design aesthetic, like LUX or FLATLY
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.LUX], suppress_callback_exceptions=True)
sidebar = html.Div(
    [
        html.H2('APE•X', className='display-logo'),
        html.Hr(),
        html.P(
            "Test your portfolio and backtesting strategies", className="lead"
        ),
        dbc.Nav(
            [
                dbc.NavLink("Backtesting", href="/backtesting", active="exact"),
                dbc.NavLink("Investment Portfolio", href="/portfolio", active="exact"),
                # Add more links as needed
            ],
            vertical=True,
            pills=True,
        ),
        html.Div(
            [l_openai_key,
             l_settings_scale_toggle], 
            style={'position': 'absolute', 'bottom': '10px'})  # Fixes the input at the bottom
    ],
    style={
        'position': 'fixed',
        'height':'100vh',
        'top': 0,
        'left': 0,
        'bottom': 0,
        'width': '21%',
        'padding': '20px',
        'backgroundColor': '#f8f9fa'
    },
)

content = html.Div(id="page-content", style={'marginLeft': '20%'})

app.layout = html.Div([dcc.Location(id="url"), sidebar, content])

# Main callback
@app.callback(Output('page-content', 'children'),
              [Input('url', 'pathname')])
def render_page_content(pathname):
    if pathname == "/backtesting":
        return l1
    elif pathname == "/portfolio":
        return l2

# Register all tab callbacks
rc_openai_key(app)
rc_gpt(app)
rc2(app)
rc1(app)

# Run
if __name__ == '__main__':
    app.run_server(debug=True)
