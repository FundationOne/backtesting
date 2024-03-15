import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output

from backtesting_sim import layout as l1, register_callbacks as rc1
from portfolio_sim import layout as l2, register_callbacks as rc2
from gpt_functionality import layout as l_gpt, register_callbacks as rc_gpt

# Choose a theme closer to Apple's design aesthetic, like LUX or FLATLY
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.LUX])
app.config.suppress_callback_exceptions = True

# Main layout
app.layout = dbc.Container(
    [
        html.Div(l_gpt, style={'padding': '20px'}),  # Add padding for layout separation
        dcc.Tabs(
            id="tabs", 
            children=[
                dcc.Tab(label='Backtesting', value='tab-1', style={'fontWeight': 'bold'}),
                dcc.Tab(label='Investment Portfolio', value='tab-2', style={'fontWeight': 'bold'}),
            ],
            style={'fontFamily': 'Sans-serif'}  # Cleaner typography
        ),
        html.Div(id='tabs-content', style={'padding': '20px'})  # Add padding around content
    ],
    fluid=True,  # Use the entire width
    style={'padding': '20px'}  # Padding around the container for better spacing
)

# Main callback
@app.callback(Output('tabs-content', 'children'),
              [Input('tabs', 'value')])
def render_content(tab):
    if tab == 'tab-1':
        return l1
    elif tab == 'tab-2':
        return l2

# Register all tab callbacks
rc2(app)
rc1(app)
rc_gpt(app)

# Run
if __name__ == '__main__':
    app.run_server(debug=True)
