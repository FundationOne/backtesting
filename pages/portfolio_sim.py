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

# Modern layout
layout = html.Div([
    # Page Header
    html.Div([
        html.H4([
            html.I(className="bi bi-wallet2 me-2"),
            "Portfolio Simulation"
        ], className="page-title"),
        html.P("Simulate long-term portfolio growth with withdrawals and taxes", className="page-subtitle")
    ], className="page-header"),
    
    # Main Content
    dbc.Row([
        # Left Column - Parameters
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-sliders me-2"),
                    "Simulation Parameters"
                ], className="card-header-modern"),
                dbc.CardBody([
                    # Investment Section
                    html.Label("Starting Investment", className="input-label"),
                    dbc.InputGroup([
                        dbc.InputGroupText("€", className="input-group-text"),
                        dbc.Input(
                            id="input-current-value", 
                            type="number", 
                            value=default_current_value,
                            className="compact-input"
                        ),
                    ], size="sm", className="mb-2"),
                    
                    html.Label("Annual Growth Rate", className="input-label"),
                    dbc.InputGroup([
                        dbc.Input(
                            id="input-annual-growth-rate", 
                            type="number", 
                            value=default_annual_growth_rate,
                            className="compact-input"
                        ),
                        dbc.InputGroupText("%", className="input-group-text"),
                    ], size="sm", className="mb-3"),
                    
                    html.Hr(className="my-2"),
                    
                    # Withdrawal Section
                    html.Label("Withdrawal Type", className="input-label"),
                    dbc.RadioItems(
                        id='withdrawal-type',
                        options=[
                            {'label': 'Fixed Sum', 'value': 'fixed'},
                            {'label': 'Percentage', 'value': 'percentage'}
                        ],
                        value='fixed',
                        inline=True,
                        className="mb-2"
                    ),
                    
                    html.Label("Annual Withdrawal", className="input-label"),
                    dbc.InputGroup([
                        dbc.Input(
                            id="input-annual-withdrawal", 
                            type="number", 
                            value=default_annual_withdrawal,
                            className="compact-input"
                        ),
                        dbc.InputGroupText(id="withdrawal-unit", children="€", className="input-group-text"),
                    ], size="sm", className="mb-3"),
                    
                    html.Hr(className="my-2"),
                    
                    # Time Frame Section
                    html.Label("Simulation Time Frame", className="input-label"),
                    dcc.Dropdown(
                        id="simulation-time-frame",
                        options=[
                            {'label': 'Custom Years', 'value': 'custom'},
                            {'label': 'S&P 500 Historical', 'value': 'sp500'}
                        ],
                        value='custom',
                        clearable=False,
                        className="compact-dropdown mb-2"
                    ),
                    
                    html.Div(id="custom-years-input", children=[
                        html.Label("Years to Simulate", className="input-label"),
                        dbc.Input(
                            id="input-years-to-simulate", 
                            type="number", 
                            value=default_years_to_simulate,
                            className="compact-input mb-2",
                            size="sm"
                        )
                    ]),
                    
                    html.Div(id="sp500-year-input", style={'display': 'none'}, children=[
                        html.Label("Starting Year (S&P 500)", className="input-label"),
                        dcc.Dropdown(
                            id="input-sp500-start-year",
                            options=[{'label': str(year), 'value': year} for year in range(1928, 2026)],
                            value=1970,
                            clearable=False,
                            className="compact-dropdown mb-2"
                        )
                    ]),
                    
                    html.Hr(className="my-2"),
                    
                    # Tax Section
                    html.Label("Capital Gains Tax Rate", className="input-label"),
                    dbc.InputGroup([
                        dbc.Input(
                            id="input-tax-rate", 
                            type="number", 
                            value=25,
                            className="compact-input"
                        ),
                        dbc.InputGroupText("%", className="input-group-text"),
                    ], size="sm", className="mb-2"),
                    
                    html.Label("Taxation Method", className="input-label"),
                    dcc.Dropdown(
                        id="input-tax-method",
                        options=[{'label': 'FIFO (First In, First Out)', 'value': 'FIFO'}],
                        value=default_tax_method,
                        clearable=False,
                        className="compact-dropdown"
                    )
                ], className="py-2")
            ], className="card-modern")
        ], md=4, className="mb-3"),
        
        # Right Column - Results
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-graph-up me-2"),
                    "Portfolio Projection"
                ], className="card-header-modern"),
                dbc.CardBody([
                    dcc.Graph(
                        id='investment-graph',
                        config={'displayModeBar': False, 'displaylogo': False},
                        style={"height": "300px"}
                    )
                ], className="py-2")
            ], className="card-modern mb-2"),
            
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-table me-2"),
                    "Year-by-Year Breakdown"
                ], className="card-header-modern"),
                dbc.CardBody([
                    dash_table.DataTable(
                        id='table',
                        columns=[{"name": i, "id": i} for i in df_dash.columns],
                        data=df_dash.to_dict('records'),
                        style_table={'height': '350px', 'overflowY': 'auto'},
                        style_cell={
                            'textAlign': 'left',
                            'padding': '8px 12px',
                            'fontFamily': 'Inter, sans-serif',
                            'fontSize': '0.75rem',
                            'border': 'none'
                        },
                        style_header={
                            'fontWeight': '600',
                            'backgroundColor': '#f8fafc',
                            'borderBottom': '1px solid #e5e7eb',
                            'fontSize': '0.7rem',
                            'textTransform': 'uppercase',
                            'color': '#6b7280'
                        },
                        style_data={
                            'borderBottom': '1px solid #f3f4f6'
                        },
                        style_data_conditional=[
                            {
                                'if': {'row_index': 'odd'},
                                'backgroundColor': '#fafbfc'
                            }
                        ]
                    )
                ], className="py-2")
            ], className="card-modern")
        ], md=8)
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
        
        # Modern color palette
        colors = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
        
        numeric_columns = df.select_dtypes(include=['float', 'int']).columns.drop('Year')
        
        for i, col in enumerate(numeric_columns):
            visible = True if col != 'Ending Value' else 'legendonly'
            fig.add_trace(go.Scatter(
                x=df['Year'], 
                y=df[col], 
                mode='lines+markers', 
                name=col,
                visible=visible,
                line=dict(color=colors[i % len(colors)], width=2),
                marker=dict(size=6)
            ))
            
        # Modern chart styling
        fig.update_layout(
            title=None,
            xaxis_title='Year',
            yaxis_title='Amount ($)',
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(size=12)
            ),
            margin=dict(l=0, r=0, t=40, b=0),
            plot_bgcolor='white',
            paper_bgcolor='white',
            font=dict(family="Inter, sans-serif", color="#1e293b"),
            xaxis=dict(
                showgrid=True,
                gridcolor='#f1f5f9',
                linecolor='#e2e8f0'
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor='#f1f5f9',
                linecolor='#e2e8f0',
                tickformat='$,.0f'
            ),
            hovermode='x unified',
            transition_duration=300
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