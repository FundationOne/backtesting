import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import pandas as pd
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate

def simulate_portfolio(current_value, annual_growth_rate, annual_withdrawal, years_to_simulate, tax_rate=0.25, tax_method='FIFO'):
    # Initialize DataFrame
    df = pd.DataFrame(index=range(1, years_to_simulate + 1),
                      columns=["Year", "Starting Value", "Withdrawals", "Growth", "Taxes Paid", "Ending Value"])
    df['Year'] = range(1, years_to_simulate + 1)

    original_principal = current_value  # Keep track of the original investment
    cumulative_growth = 0  # To track total growth over the years

    for year in range(1, years_to_simulate + 1):
        starting_value = current_value
        growth = current_value * annual_growth_rate
        cumulative_growth += growth
        
        # Determine the portion of withdrawal that is from growth (and taxable) vs principal
        if original_principal > 0:
            withdrawal_from_principal = min(annual_withdrawal, original_principal)
            original_principal -= withdrawal_from_principal
            withdrawal_from_growth = max(0, annual_withdrawal - withdrawal_from_principal)
        else:
            withdrawal_from_growth = annual_withdrawal
        
        # Calculate taxes if withdrawing from growth
        if withdrawal_from_growth > 0 and cumulative_growth > 0:
            taxable_amount = min(withdrawal_from_growth, cumulative_growth)
            taxes_paid = taxable_amount * tax_rate
            cumulative_growth -= taxable_amount  # Reduce cumulative growth by the taxed portion
        else:
            taxes_paid = 0
        
        # Update current value after accounting for growth, withdrawal, and taxes
        current_value = starting_value + growth - annual_withdrawal - taxes_paid
        df.loc[year] = [year, starting_value, annual_withdrawal, growth, taxes_paid, current_value]

    # Convert numeric columns to float and round to 2 decimal places
    numeric_cols = ['Starting Value', 'Withdrawals', 'Growth', 'Taxes Paid', 'Ending Value']
    df[numeric_cols] = df[numeric_cols].astype(float).round(2)

    return df

# Create the initial DataFrame with default values
default_current_value = 700000
default_annual_growth_rate = 10
default_annual_withdrawal = 30000
default_years_to_simulate = 30
default_tax_rate = 25
default_tax_method = 'FIFO'

df_dash = simulate_portfolio(default_current_value, default_annual_growth_rate/100, default_annual_withdrawal, default_years_to_simulate, default_tax_rate/100, default_tax_method)

# Tab layout
layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            dbc.Card([
                # dbc.CardHeader(html.H3("Input Parameters")),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Label("Starting Investment", html_for="input-current-value", width=12),
                        dbc.Col([
                            dcc.Input(id="input-current-value", type="number", value=default_current_value)
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Label("Annual Growth Rate %", html_for="input-annual-growth-rate", width=12),
                        dbc.Col([
                            dcc.Input(id="input-annual-growth-rate", type="number", value=default_annual_growth_rate)
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Label("Annual Withdrawal", html_for="input-annual-withdrawal", width=12),
                        dbc.Col([
                            dcc.Input(id="input-annual-withdrawal", type="number", value=default_annual_withdrawal)
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Label("Years to Simulate", html_for="input-years-to-simulate", width=12),
                        dbc.Col([
                            dcc.Input(id="input-years-to-simulate", type="number", value=default_years_to_simulate)
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Label("Capital Gains Tax Rate %", html_for="input-tax-rate", width=12),
                        dbc.Col([
                            dcc.Input(id="input-tax-rate", type="number", value=25)  # Default tax rate 25%
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Label("Taxation Method", html_for="input-tax-method", width=12),
                        dbc.Col([
                            dcc.Dropdown(id="input-tax-method",
                                        options=[{'label': 'FIFO', 'value': 'FIFO'}],
                                        value=default_tax_method)
                        ], width=12)
                    ])
                ])
            ], style={"border":"unset"})
        ], sm=12, md=4),
        dbc.Col([
            dbc.Card([
                # dbc.CardHeader(html.H3("Investment Portfolio Over " + str(default_years_to_simulate) + " Years")),
                dbc.CardBody([
                    dcc.Graph(id='investment-graph'),
                    dash_table.DataTable(
                        id='table',
                        columns=[{"name": i, "id": i} for i in df_dash.columns],
                        data=df_dash.to_dict('records'),
                        style_table={'height': '400px', 'overflowY': 'auto'},
                        style_cell={'textAlign': 'left'}
                    )
                ])
            ])
        ], sm=12, md=8)
    ])
])

def register_callbacks(app):
    @app.callback(
        Output('investment-graph', 'figure'),
        [Input('table', 'data')]
    )
    def update_graph(data):
        if data is None:
            raise PreventUpdate
        
        df = pd.DataFrame(data)
        
        fig = go.Figure()
        
        numeric_columns = df.select_dtypes(include=['float', 'int']).columns.drop('Year')
        
        for col in numeric_columns:
            fig.add_trace(go.Scatter(x=df['Year'], y=df[col], mode='lines+markers', name=col))
        
        # Update the layout of the figure
        fig.update_layout(
            title='Investment Portfolio Simulation Over Years',
            xaxis_title='Year',
            yaxis_title='Amount',
            legend_title='Metric',
            transition_duration=500
        )
        
        return fig


    # Callback to update the DataFrame and table when parameters change
    @app.callback(
        [Output('table', 'data'),
        Output('table', 'columns')],
        [Input('input-current-value', 'value'),
        Input('input-annual-growth-rate', 'value'),
        Input('input-annual-withdrawal', 'value'),
        Input('input-years-to-simulate', 'value'),
        Input('input-tax-rate', 'value'),
        Input('input-tax-method', 'value')], 
        State('table', 'data')
    )
    def update_table(current_value, annual_growth_rate, annual_withdrawal, years_to_simulate, tax_rate, tax_method, existing_data):
        if None in [current_value, annual_growth_rate, annual_withdrawal, years_to_simulate, tax_rate, tax_method]:
            return existing_data, [{"name": i, "id": i} for i in df_dash.columns]

        df_dash = simulate_portfolio(current_value, annual_growth_rate/100, annual_withdrawal, years_to_simulate, tax_rate/100, tax_method)
        return df_dash.to_dict('records'), [{"name": i, "id": i} for i in df_dash.columns]