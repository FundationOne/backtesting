import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import pandas as pd
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import yfinance as yf

def simulate_portfolio(current_value, annual_growth_rate, withdrawal_type, annual_withdrawal, years_to_simulate, tax_rate=0.25, tax_method='FIFO', sp500_start_year=None):
    if sp500_start_year:
        # Fetch S&P500 data
        sp500 = yf.Ticker("^GSPC")
        sp500_data = sp500.history(start=f"{sp500_start_year}-01-01")
        annual_returns = sp500_data['Close'].resample('YE').last().pct_change().dropna()
        years_to_simulate = len(annual_returns)

    df = pd.DataFrame(index=range(1, years_to_simulate + 1),
                      columns=["Year", "Portfolio Value", "Growth", "Withdrawals", "Taxes Paid", "Ending Value", "Cost Basis"])
    df['Year'] = range(1, years_to_simulate + 1)

    cost_basis = current_value  # Initialize cost basis

    for year in range(1, years_to_simulate + 1):
        starting_value = current_value
        if sp500_start_year:
            growth_rate = annual_returns.iloc[year-1]
        else:
            growth_rate = annual_growth_rate
        growth = current_value * growth_rate
        current_value += growth  # Apply growth before withdrawal

        # Calculate withdrawal amount based on type
        if withdrawal_type == 'percentage':
            withdrawal_amount = current_value * (annual_withdrawal / 100)
        else:
            withdrawal_amount = annual_withdrawal

        # Calculate the taxable gain
        total_gain = max(0, current_value - cost_basis)
        gain_ratio = total_gain / current_value if current_value > 0 else 0
        taxable_amount = withdrawal_amount * gain_ratio
        taxes_paid = max(0, taxable_amount * tax_rate)

        # Update current value and cost basis after accounting for withdrawal and taxes
        current_value -= (withdrawal_amount + taxes_paid)
        cost_basis_reduction = cost_basis * (withdrawal_amount / starting_value)
        cost_basis -= cost_basis_reduction

        # Record the data for the current year
        df.loc[year] = [year, starting_value, growth, withdrawal_amount, taxes_paid, current_value, cost_basis]

    # Convert numeric columns to float and round to 2 decimal places
    numeric_cols = ['Portfolio Value', 'Growth', 'Withdrawals', 'Taxes Paid', 'Ending Value', 'Cost Basis']
    df[numeric_cols] = df[numeric_cols].astype(float).round(2)

    return df

# Create the initial DataFrame with default values
default_current_value = 700000
default_annual_growth_rate = 7
default_annual_withdrawal = 30000
default_years_to_simulate = 30
default_tax_rate = 25
default_tax_method = 'FIFO'
default_withdrawal_type = 'fixed'

df_dash = simulate_portfolio(default_current_value, default_annual_growth_rate/100, default_withdrawal_type, default_annual_withdrawal, default_years_to_simulate, default_tax_rate/100, default_tax_method)

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
                        dbc.Label("Withdrawal Type", html_for="withdrawal-type", width=12),
                        dbc.Col([
                            dcc.RadioItems(
                                id='withdrawal-type',
                                options=[
                                    {'label': 'Fixed Sum', 'value': 'fixed'},
                                    {'label': 'Percentage of Portfolio', 'value': 'percentage'}
                                ],
                                value='fixed',
                                inline=True
                            )
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Label("Annual Withdrawal", html_for="input-annual-withdrawal", width=12),
                        dbc.Col([
                            html.Div([
                                dcc.Input(id="input-annual-withdrawal", type="number", value=default_annual_withdrawal, style={"width": "calc(100% - 60px)", "display": "inline-block"}),
                                html.Span(id="withdrawal-unit", style={"display": "inline-block", "width": "30px", "text-align": "center"})
                            ], style={"display": "flex", "alignItems": "center"})
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Label("Simulation Time Frame", html_for="simulation-time-frame", width=12),
                        dbc.Col([
                            dcc.Dropdown(
                                id="simulation-time-frame",
                                options=[
                                    {'label': 'Custom Years', 'value': 'custom'},
                                    {'label': 'S&P500 Historical', 'value': 'sp500'}
                                ],
                                value='custom'
                            )
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Div(id="custom-years-input", children=[
                                dbc.Label("Years to Simulate", html_for="input-years-to-simulate", width=12),
                                dcc.Input(id="input-years-to-simulate", type="number", value=default_years_to_simulate)
                            ])
                        ], width=12),
                        dbc.Col([
                            html.Div(id="sp500-year-input", style={'display': 'none'}, children=[
                                dbc.Label("Starting Year (S&P500)", html_for="input-sp500-start-year", width=12),
                                dcc.Dropdown(
                                    id="input-sp500-start-year",
                                    options=[{'label': str(year), 'value': year} for year in range(1928, 2024)],  # Adjust the range as needed
                                    value=1970  # Default starting year
                                )
                            ])
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
        ], sm=12, md=4, style={"padding":"0px"}),
        dbc.Col([
            dbc.Card([
                # dbc.CardHeader(html.H3("Investment Portfolio Over " + str(default_years_to_simulate) + " Years")),
                dbc.CardBody([
                    dcc.Graph(id='investment-graph'),
                    dash_table.DataTable(
                        id='table',
                        columns=[{"name": i, "id": i} for i in df_dash.columns],
                        data=df_dash.to_dict('records'),
                        style_table={'height': '600px', 'overflowY': 'auto'},
                        style_cell={'textAlign': 'left'}
                    )
                ])
            ])
        ], sm=12, md=8, style={"padding":"0px"})
    ])
])

def register_callbacks(app):
    @app.callback(
        Output('withdrawal-unit', 'children'),
        [Input('withdrawal-type', 'value')]
    )
    def update_withdrawal_unit(withdrawal_type):
        return '$' if withdrawal_type == 'fixed' else '%'

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
            visible = True if col != 'Ending Value' else 'legendonly'
            fig.add_trace(go.Scatter(
                x=df['Year'], 
                y=df[col], 
                mode='lines+markers', 
                name=col,
                visible=visible
            ))
            
        # Update the layout of the figure
        fig.update_layout(
            title='Investment Portfolio Simulation Over Years',
            xaxis_title='Year',
            yaxis_title='Amount',
            legend_title='Metric',
            transition_duration=500
        )
        
        return fig
    
    @app.callback(
        [Output("custom-years-input", "style"),
        Output("sp500-year-input", "style")],
        [Input("simulation-time-frame", "value")]
    )
    def toggle_time_frame_input(selected_time_frame):
        if selected_time_frame == 'custom':
            return {'display': 'block'}, {'display': 'none'}
        else:
            return {'display': 'none'}, {'display': 'block'}
        
    @app.callback(
        [Output('investment-graph', 'figure', allow_duplicate=True)],
        [Input('scale-toggle', 'value'),
         State('investment-graph', 'figure')],
         prevent_initial_call=True)
    def update_investment_fig_scale(scale, fig_dict):
        if scale is None:
            raise PreventUpdate
        
        fig = go.Figure(fig_dict)
        fig.update_layout(yaxis_type=scale, yaxis_autorange=True)

        return [fig]

    # Callback to update the DataFrame and table when parameters change
    @app.callback(
        [Output('table', 'data'),
         Output('table', 'columns')],
        [Input('input-current-value', 'value'),
         Input('input-annual-growth-rate', 'value'),
         Input('withdrawal-type', 'value'), 
         Input('input-annual-withdrawal', 'value'),
         Input('simulation-time-frame', 'value'),
         Input('input-years-to-simulate', 'value'),
         Input('input-sp500-start-year', 'value'),
         Input('input-tax-rate', 'value'),
         Input('input-tax-method', 'value')],
        State('table', 'data')
    )
    def update_table(current_value, annual_growth_rate, withdrawal_type, annual_withdrawal, simulation_time_frame, years_to_simulate, sp500_start_year, tax_rate, tax_method, existing_data):
        if None in [current_value, annual_growth_rate, withdrawal_type, annual_withdrawal, simulation_time_frame, tax_rate, tax_method]:
            return existing_data, [{"name": i, "id": i} for i in df_dash.columns]
    
        if simulation_time_frame == 'custom':
            df_dash = simulate_portfolio(current_value, annual_growth_rate/100, withdrawal_type, annual_withdrawal, years_to_simulate, tax_rate/100, tax_method)
        else:
            df_dash = simulate_portfolio(current_value, None, withdrawal_type, annual_withdrawal, None, tax_rate/100, tax_method, sp500_start_year)
    
        return df_dash.to_dict('records'), [{"name": i, "id": i} for i in df_dash.columns]