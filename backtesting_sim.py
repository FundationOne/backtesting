import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table, ctx
from dash.dependencies import Input, Output, State, ALL
import pandas as pd
import numpy as np
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import ta
import os
from utils import *

from dash.exceptions import PreventUpdate
from pathlib import Path
from conf import *

from rule_gen_functionality import *

# Function to fetch historical data for Bitcoin
def convert_volume(value):
    if isinstance(value, str):  # Ensure the value is processed as a string
        value = value.replace(',', '').upper()  # Remove commas, standardize on uppercase
        if 'K' in value:
            return float(value.replace('K', '')) * 1e3
        elif 'M' in value:
            return float(value.replace('M', '')) * 1e6
        elif 'B' in value:
            return float(value.replace('B', '')) * 1e9
    return pd.to_numeric(value, errors='coerce')  # Safely convert non-string or malformed values

    
def fetch_historical_data(csv_file_path):
    btc_data_raw = pd.read_csv(csv_file_path, parse_dates=['Date'], index_col='Date', dtype={'Vol.': str})
    btc_data_raw.sort_index(inplace=True)
    btc_data = pd.DataFrame(index=btc_data_raw.index)

    # Clean and convert data types
    btc_data['price'] = btc_data_raw['Price'].str.replace(',', '').astype(float)
    btc_data['open'] = btc_data_raw['Open'].str.replace(',', '').astype(float)
    btc_data['high'] = btc_data_raw['High'].str.replace(',', '').astype(float)
    btc_data['low'] = btc_data_raw['Low'].str.replace(',', '').astype(float)
    btc_data['volume'] = btc_data_raw['Vol.'].apply(convert_volume)

    return btc_data

def fetch_onchain_indicators(csv_file_path):
    base_dir = Path(csv_file_path)
    data_frames = []

    for file_path in base_dir.rglob('*.csv'):
        if file_path.name == 'price.csv' or file_path.name == '30d_sma.csv' or file_path.name == '365d_sma.csv':
            continue  # Skip these files
        column_name = '__'.join(file_path.relative_to(base_dir).with_suffix('').parts[1:])
        df = pd.read_csv(file_path, parse_dates=['date'])
        df.set_index('date', inplace=True)
        df.columns = [column_name]
        data_frames.append(df)

    full_df = pd.concat(data_frames, axis=1)
    return full_df

def add_historical_indicators(btc_data):
    btc_data['last_highest'] = btc_data['price'].cummax().shift(1)
    btc_data['last_lowest'] = btc_data['price'].cummin().shift(1)
    btc_data['sma_10'] = ta.trend.sma_indicator(btc_data['price'], window=10)
    btc_data['sma_20'] = ta.trend.sma_indicator(btc_data['price'], window=20)
    btc_data['sma_50'] = ta.trend.sma_indicator(btc_data['price'], window=50)
    btc_data['sma_200'] = ta.trend.sma_indicator(btc_data['price'], window=200)
    btc_data['sma_20_week'] = ta.trend.sma_indicator(btc_data['price'], window=140)
    btc_data['sma_100_week'] = ta.trend.sma_indicator(btc_data['price'], window=700)
    btc_data['rsi_14'] = ta.momentum.rsi(btc_data['price'], window=14)
    btc_data['macd'] = ta.trend.macd_diff(btc_data['price'])
    btc_data['bollinger_upper'], btc_data['bollinger_lower'] = ta.volatility.bollinger_hband(btc_data['price']), ta.volatility.bollinger_lband(btc_data['price'])
    btc_data['ema_8'] = ta.trend.ema_indicator(btc_data['price'], window=8)
    btc_data['ema_20'] = ta.trend.ema_indicator(btc_data['price'], window=20)
    btc_data['ema_50'] = ta.trend.ema_indicator(btc_data['price'], window=50)
    btc_data['ema_200'] = ta.trend.ema_indicator(btc_data['price'], window=200)
    btc_data['stochastic_oscillator'] = ta.momentum.stoch(btc_data['high'], btc_data['low'], btc_data['price'], window=14, smooth_window=3)
    btc_data['atr'] = ta.volatility.average_true_range(btc_data['high'], btc_data['low'], btc_data['price'], window=14)
    btc_data['on_balance_volume'] = ta.volume.on_balance_volume(btc_data['price'], btc_data['volume'])
    btc_data['momentum_14'] = ta.momentum.roc(btc_data['price'], window=14)
    btc_data['percent_change'] = btc_data['price'].pct_change()
    btc_data['volatility'] = btc_data['atr'] / btc_data['price'] * 100
    btc_data['atr_percent'] = (ta.volatility.AverageTrueRange(btc_data['high'], btc_data['low'], btc_data['price']).average_true_range() / btc_data['price']) * 100
    ichimoku = ta.trend.IchimokuIndicator(btc_data['high'], btc_data['low'])
    btc_data['ichimoku_a'] = ichimoku.ichimoku_a()
    btc_data['ichimoku_b'] = ichimoku.ichimoku_b()
    btc_data['parabolic_sar'] = ta.trend.PSARIndicator(btc_data['high'], btc_data['low'], btc_data['price']).psar()
    btc_data['support'] = find_support(btc_data['price'], window=20)
    btc_data['resistance'] = find_resistance(btc_data['price'], window=20)
    btc_data['volume_spike'] = volume_spike_detection(btc_data['volume'], window=20, threshold=2)
    btc_data['days_since_last_halving'] = btc_data.index.to_series().apply(days_since_last_halving)
    btc_data['power_law_price_1y_window'] = rolling_power_law_price_windowed(btc_data, window_size=365)
    btc_data['power_law_price_4y_window'] = rolling_power_law_price_windowed(btc_data, window_size=365*4)
    btc_data['power_law_price'] = rolling_power_law_price(btc_data)

    return btc_data

def lump_sum_and_hold_strategy(btc_data, starting_investment):
    # Assuming starting investment is made on the first day of the given data
    initial_price = btc_data['price'].iloc[0]
    btc_bought = starting_investment / initial_price
    portfolio_value = btc_bought * btc_data['price']
    return portfolio_value

def monthly_dca_strategy(btc_data, starting_investment):
    # Calculate the total number of months
    total_months = ((btc_data.index[-1] - btc_data.index[0]).days) // 30  # Approximate month count
    
    # Calculate monthly investment
    monthly_investment = starting_investment / total_months if total_months else starting_investment
    
    # Initial setup
    btc_owned = 0
    portfolio_value = pd.Series(index=btc_data.index, dtype=float)
    
    for i in range(1, len(btc_data)):
        # Assume monthly investments happen at the start of each month
        current_date = btc_data.index[i]
        previous_date = btc_data.index[i-1]
        
        # Check if a new month has started
        if current_date.month != previous_date.month:
            btc_owned += monthly_investment / btc_data['price'].iloc[i]
        
        # Update portfolio value for the current day
        portfolio_value.iloc[i] = btc_owned * btc_data['price'].iloc[i]
    
    portfolio_value.iloc[0] = 0  # Start with a 0 investment
    portfolio_value.ffill(inplace=True)  # Forward fill the portfolio value for days without transactions

    return portfolio_value
# Function to execute trading strategy
def execute_strategy(btc_data, starting_investment, start_date, buying_rule, selling_rule, trade_amount, transaction_fee, taxation_method, tax_amount):
    if pd.to_datetime(start_date) not in btc_data.index:
        start_date = btc_data.index[0].strftime('%Y-%m-%d')
        print("Start date is out of the dataset's date range.")

    # Filter the data to start from the given start date
    btc_data = btc_data[start_date:]

    available_cash = starting_investment
    btc_owned = 0
    transactions = []
    btc_purchases = []  # Keep track of BTC purchases for FIFO taxation
    portfolio_value_over_time = pd.Series(index=btc_data.index, dtype=float)
    
    if not buying_rule and not selling_rule:
        return pd.DataFrame(transactions), portfolio_value_over_time
    
    for i in range(len(btc_data)):
        current_data = btc_data.iloc[:i+1]
        current_price = current_data['price'].iloc[-1]
        date = current_data.index[-1]

        # Calculate current portfolio value (BTC holdings + cash)
        current_portfolio_value = btc_owned * current_price + available_cash
        portfolio_value_over_time[date] = current_portfolio_value

        # Prepare the context
        context = {
            'historic': lambda col: current_data.get(col, []),#all up to today
            'current': lambda col: current_data[col].iloc[-1],
            'n_days_ago': lambda col, n: current_data[col].iloc[-n-1],
            'current_portfolio_value': current_portfolio_value,
            'portfolio_value_over_time': portfolio_value_over_time,
            'available_cash': available_cash,
            'btc_owned': btc_owned,
            'current_date': date.strftime('%Y-%m-%d'),
            'current_index': i,
            'np':np,
            'pd':pd
        }

        buy_eval = False
        sell_eval = False
        
        try:
            # buy_eval = eval(buying_rule, {"__builtins__": {'min': min, 'max': max, 'all': all, 'any': any}}, context)
            # sell_eval = eval(selling_rule, {"__builtins__": {'min': min, 'max': max, 'all': all, 'any': any}}, context)
            if buying_rule:
                buy_eval = eval(buying_rule, context)
            if selling_rule:
                sell_eval = eval(selling_rule, context)

        except TypeError as te:
            if not sell_eval:
                print(f"Rule is invalid. Type Error evaluating rules: {te} >>> {selling_rule}")
            if not buy_eval:
                print(f"Rule is invalid. Type Error evaluating rules: {te} >>> {buying_rule}")
            return
        except Exception as e:
            # print(context['historic']('price'))
            # print(context['current']('price'))
            if not sell_eval:
                print(f"Sell Rule could not be applied to this day: {e} >>> {selling_rule}")
            if not buy_eval:
                print(f"Buy Rule could not be applied to this day: {e} >>> {buying_rule}")
            continue

        if buy_eval:
            # Calculate the maximum number of BTC that can be bought with available cash
            max_btc_to_buy = (available_cash - transaction_fee) / current_price
            
            # Buy the lesser of trade_amount or max_btc_to_buy
            btc_to_buy = min(trade_amount / current_price, max_btc_to_buy)
            
            available_cash -= (btc_to_buy * current_price + transaction_fee)
            btc_owned += btc_to_buy
            transactions.append({'Date': date.strftime('%Y-%m-%d'), 'Action': 'BUY', 'BTC': round(btc_to_buy,12), 'price': current_price, 'Owned Cash': round(available_cash, 2), 'Owned BTC': round(btc_owned,12), 'Taxable Amount': ''})
            btc_purchases.append({"date": date.strftime('%Y-%m-%d'), "amount": btc_to_buy, "price": current_price})

        elif sell_eval and btc_owned > 0:
            btc_to_sell = min(trade_amount / current_price, btc_owned)
            sale_proceeds = btc_to_sell * current_price

            if taxation_method == "FIFO":
                taxable_amount = 0
                for i in range(int(btc_to_sell)):
                    if btc_purchases:
                        purchase = btc_purchases.pop(0)
                        holding_period = (date - purchase["date"]).days
                        if holding_period < 365:
                            taxable_amount += (current_price - purchase["price"]) * (tax_amount / 100)

            available_cash += sale_proceeds - taxable_amount - transaction_fee
            btc_owned -= btc_to_sell
            transactions.append({'Date': date.strftime('%Y-%m-%d'), 'Action': 'SELL', 'BTC': round(btc_to_sell,12), 'price': current_price, 'Owned Cash': round(available_cash, 2), 'Owned BTC': round(btc_owned,12), 'Taxable Amount': round(taxable_amount, 2)})

    transactions_df = pd.DataFrame(transactions)

    return transactions_df, portfolio_value_over_time


loading_component = dbc.Spinner(color="primary", children="Running Backtest...")

layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader([
                            dbc.Col(html.H5("Backtesting Parameters", className="mb-0"), width={"size": 10, "offset": 0}),
                            dbc.Col(dbc.Button(
                                        html.Span("▼", id="collapse-icon"),
                                        id="collapse-button",
                                        className="ml-auto",
                                        color="primary",
                                        n_clicks=0,
                                    ), width={"size": 2, "offset": 0}),
                        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}),
                        dbc.Collapse(
                            dbc.CardBody([
                                dbc.Row([
                                    dbc.Label("Available Cash $", html_for="input-starting-investment", width=12),
                                    dbc.Col(
                                        dcc.Input(id="input-starting-investment", type="number", value=10000),
                                        width=12,
                                    ),
                                ]),
                                dbc.Row([
                                    dbc.Label("Trade Amount $", html_for="input-trade-amount", width=12),
                                    dbc.Col(
                                        dcc.Input(id="input-trade-amount", type="number", value=100),
                                        width=12,
                                    ),
                                ]),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Label("Transaction Fee $", html_for="input-transaction-fee", width=12),
                                        dcc.Input(id="input-transaction-fee", type="number", value=0.01, step=0.01)
                                    ], width=12),
                                ]),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Label("Starting Date", html_for="input-starting-date", width=12),
                                        dcc.DatePickerSingle(id="input-starting-date", date='2018-01-01')
                                    ], width=12),
                                ]),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Label("Taxation Method", html_for="taxation-method-dropdown", width=12),
                                        dcc.Dropdown(
                                            id="taxation-method-dropdown",
                                            options=[{"label": "FIFO", "value": "FIFO"}],
                                            value="FIFO",
                                            clearable=False
                                        )
                                    ], width=12),
                                ]),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Label("Tax Amount (%)", html_for="input-tax-amount", width=12),
                                        dcc.Input(id="input-tax-amount", type="number", value=25, min=0, max=100)
                                    ], width=12),
                                ]),
                            ]),
                            id="collapse",
                            is_open=True,
                        ),
                        dbc.CardHeader([
                            dbc.Col(html.H5("BUY / SELL RULES", className="mb-0"), width={"size": 8, "offset": 0}),
                        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}),
                        dbc.Row(id="trading-rules-container"),
                        dbc.Row([
                            dbc.Col(dbc.Button("Save Rules", id="open-save-rules-modal", className="me-2 btn-secodnary", color="secondary", n_clicks=0), width={"size": 3, "offset": 1}),
                            dbc.Col(dbc.Button("Load Rules", id="open-load-rules-modal", className="me-2 btn-secodnary", color="secondary", n_clicks=0), width={"size": 3, "offset": 0}),
                            dbc.Col(create_rule_generation_button(1), width={"size": 3, "offset": 1}),
                            rule_generation_modal,
                            dbc.Col(dbc.Button("Run Backtest", id="update-backtesting-button", className="me-2 mt-4", n_clicks=0), width={"size": 6, "offset": 3})
                        ],className="mb-3", style={"marginTop":"20px"})
                    ], className="mb-3", style={"border":"unset"}
                    ), sm=12, md=4, style={"padding":"0px"}
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardBody([
                                dcc.Loading(
                                    id="loading-graph",
                                    type="default",
                                    children=dcc.Graph(id='backtesting-graph'),
                                ),
                                dcc.Loading(
                                    id="loading-table",
                                    type="default",
                                    children=dash_table.DataTable(
                                        id='backtesting-table',
                                        style_table={'height': '400px', 'overflowY': 'auto'},
                                        style_cell={'textAlign': 'left'},
                                    )
                                )
                            ]),
                        ]
                    ),
                    sm=12, md=8, style={"padding":"0px"}
                ),
            ]
        ),
        dcc.Store(id="saved-rules-store", storage_type="local"),
        save_rules_modal(),
        load_rules_modal(),
    ],
    fluid=True,
)

def register_callbacks(app):
    @app.callback(
        [Output('backtesting-table', 'data'),
         Output('backtesting-table', 'columns'),
         Output('backtesting-graph', 'figure')],
        [Input('update-backtesting-button', 'n_clicks')],  # Updated trigger
        [State('input-starting-investment', 'value'),
        State('input-starting-date', 'date'),
        State("trading-rules-container", "children"),
        State("saved-rules-store", "data"),
        State('scale-toggle', 'value'),
        State('input-trade-amount', 'value'),
        State('input-transaction-fee', 'value'),
        State('taxation-method-dropdown', 'value'),  # Add this line
        State('input-tax-amount', 'value')]
    )
    def update_backtesting(n_clicks, starting_investment, start_date, children, store_data, scale, trade_amount, transaction_fee, taxation_method, tax_amount):
        if None in [starting_investment, start_date, children]:
            raise PreventUpdate
        
        if store_data:
            rules_from_ui = get_rules_from_ui(children)
            buying_rule = " or ".join(rules_from_ui.get("buying_rule", []))
            selling_rule = " or ".join(rules_from_ui.get("selling_rule", []))

        if not os.path.exists(PREPROC_FILENAME) or PREPROC_OVERWRITE:
            btc_data = fetch_historical_data('./btc_hist_prices.csv')  # Load the entire historical dataset
            btc_data = add_historical_indicators(btc_data)

            #add onchain
            onchain_data = fetch_onchain_indicators('./indicators')
            btc_data_full = btc_data.join(onchain_data, how='left')

            btc_data_full.to_csv(PREPROC_FILENAME)
            print(f"Data saved to {PREPROC_FILENAME}.")
        else:
            btc_data = pd.read_csv(PREPROC_FILENAME, parse_dates=['Date'], index_col='Date')
            print(f"Data loaded from {PREPROC_FILENAME}.")

        transactions_df, portfolio_value_over_time = execute_strategy(btc_data, starting_investment, start_date, buying_rule, selling_rule, trade_amount, transaction_fee, taxation_method, tax_amount)

        # Calculate strategies
        lump_sum_portfolio = lump_sum_and_hold_strategy(btc_data[start_date:], starting_investment)
        dca_portfolio = monthly_dca_strategy(btc_data[start_date:], starting_investment)  # Total Invest / Months

        # Plotting
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:]['price'], mode='lines', name='BTC price'))
        fig.add_trace(go.Scatter(x=lump_sum_portfolio.index, y=lump_sum_portfolio, mode='lines', name='Lump Sum & Hold Portfolio'))
        fig.add_trace(go.Scatter(x=dca_portfolio.index, y=dca_portfolio, mode='lines', name='Monthly DCA Portfolio'))
        fig.add_trace(go.Scatter(x=portfolio_value_over_time.index, y=portfolio_value_over_time, mode='lines', name='Portfolio Value'))

        # Dynamically add traces mentioned in buy and sell rules
        columns_to_plot = extract_columns_from_expression([buying_rule, selling_rule])
        for column in columns_to_plot:
            if column in btc_data.columns and column != 'price':
                fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:][column], mode='lines', name=column, visible='legendonly'))

        # highlight transactions if available
        if not transactions_df.empty:
            buy_transactions = transactions_df[transactions_df['Action'] == 'BUY']
            sell_transactions = transactions_df[transactions_df['Action'] == 'SELL']
            if not buy_transactions.empty:
                fig.add_trace(go.Scatter(x=buy_transactions['Date'], y=buy_transactions['price'], mode='markers', name='Buy', marker=dict(color='green', size=10)))
            if not sell_transactions.empty:
                fig.add_trace(go.Scatter(x=sell_transactions['Date'], y=sell_transactions['price'], mode='markers', name='Sell', marker=dict(color='red', size=10)))

        # Update the layout
        fig.update_layout(
            title='Backtesting Results Over Time',
            xaxis_title='Date',
            yaxis_title='Portfolio Value',
            legend_title='Strategy',
            height=600,
            margin=dict(b=100),
            transition_duration=500,
            plot_bgcolor='white',
            paper_bgcolor='white',
            font=dict(
                family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",  # A commonly used, web-safe font
                color="black"  # Ensures good readability against the white background
            ),
            xaxis=dict(
                showline=True,  # Show the axis line
                showgrid=True,  # Show gridlines
                linecolor='lightgrey',  # Color of the axis line
                gridcolor='lightgrey',  # Color of the gridlines; light grey is gentle on the eyes
                mirror=True  # Reflects the axis line on the opposite side as well
            ),
            yaxis=dict(
                showline=True,
                showgrid=True,
                linecolor='lightgrey',
                gridcolor='lightgrey',
                mirror=True
            ),
            legend=dict(
                title_font_family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
                font=dict(
                    family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
                    # size=10,
                    color="black"
                ),
                bgcolor="white",  # Legend background color
                bordercolor="lightgrey",  # Legend border color
                borderwidth=1,  # Border width
                orientation='h',  # Set legend orientation to horizontal
                x=0,  # Center the legend with respect to the plot's x-axis
                y=-0.7,  # Adjust y to position the legend below the x-axis
                entrywidthmode="fraction",
                entrywidth=1.0,
                xanchor='left',  # Anchor the legend's x-position to the center
                yanchor='bottom'  # Anchor the legend's y-position to the top
            )
        )

        table_data = transactions_df.to_dict('records')
        table_columns = [{"name": i, "id": i} for i in transactions_df.columns]

        fig.update_yaxes(type=scale)

        return table_data, table_columns, fig
  
    @app.callback(
        [Output('backtesting-graph', 'figure', allow_duplicate=True)],
        [Input('scale-toggle', 'value'),
         State('backtesting-graph', 'figure')],
         prevent_initial_call=True)
    def update_backtesting_fig_scale(scale, fig_dict):
        if scale is None:
            raise PreventUpdate
        
        fig = go.Figure(fig_dict)
        fig.update_layout(yaxis_type=scale, yaxis_autorange=True)

        return [fig]

    @app.callback(
        [Output("collapse", "is_open"), Output("collapse-icon", "style")],
        [Input("collapse-button", "n_clicks")],
        [State("collapse", "is_open")],
    )
    def toggle_collapse(n, is_open):
        if n:
            return not is_open, {"transform": "rotate(180deg)" if not is_open else "none"}
        return is_open, {"transform": "none"}
