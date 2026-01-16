import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output

from backtesting_sim import layout as l1, register_callbacks as rc1
from portfolio_sim import layout as l2, register_callbacks as rc2
from riskbands import layout as l3, register_callbacks as rc3  # Importing Riskbands page
from rule_gen_functionality import register_callbacks as rc_gpt
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
                dbc.NavLink("Backtesting", href="/backtesting", id="backtesting-link"),
                dbc.NavLink("Investment Portfolio", href="/portfolio", id="portfolio-link"),
                dbc.NavLink("Riskbands", href="/riskbands", id="riskbands-link"),  # Added Riskbands link
                # dbc.NavLink("Model Training", href="/hyperparams", id="hyperparams-link"),
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
        'width': '18%',
        'padding': '20px',
        'backgroundColor': '#f8f9fa'
    },
)

content = html.Div(id="page-content", style={'marginLeft': '18%'})

app.layout = html.Div([dcc.Location(id="url", refresh=False), sidebar, content])

# Main callback
@app.callback(Output('url', 'pathname'),
              [Input('url', 'pathname')])
def redirect_to_default(pathname):
    if pathname == "/" or pathname is None:
        return "/backtesting"
    return dash.no_update

@app.callback(Output('page-content', 'children'),
              [Input('url', 'pathname')])
def render_page_content(pathname):
    if pathname == "/backtesting":
        return l1
    elif pathname == "/portfolio":
        return l2
    elif pathname == "/riskbands":
        return l3  # Return Riskbands layout
    # elif pathname == "/hyperparams":
    #     return l3
    else:
        return "404 Page Not Found"

@app.callback(
    [Output("backtesting-link", "active"),
     Output("portfolio-link", "active"),
     Output("riskbands-link", "active")],  # Updated to include riskbands-link
    [Input("url", "pathname")]
)
def set_active_link(pathname):
    if pathname == "/backtesting":
        return True, False, False
    elif pathname == "/portfolio":
        return False, True, False
    elif pathname == "/riskbands":
        return False, False, True  # Set Riskbands link active
    return False, False, False

# Register all tab callbacks
rc_openai_key(app)
rc_gpt(app)
rc3(app)  # Register Riskbands callbacks
rc2(app)
rc1(app)

# Run
if __name__ == '__main__':
    app.run_server(debug=True, port=8888)
