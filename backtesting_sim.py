import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import pandas as pd
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import ta
from utils import *

from gpt_functionality import create_rule_generation_button,  rule_generation_modal

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
    btc_data = pd.read_csv(csv_file_path, parse_dates=['Date'], index_col='Date', dtype={'Vol.': str})
    
    # Clean and convert data types
    btc_data['Price'] = btc_data['Price'].str.replace(',', '').astype(float)
    btc_data['Open'] = btc_data['Open'].str.replace(',', '').astype(float)
    btc_data['High'] = btc_data['High'].str.replace(',', '').astype(float)
    btc_data['Low'] = btc_data['Low'].str.replace(',', '').astype(float)
    
    # Convert 'Vol.' to a numeric representation (assuming 'K' stands for thousands)
    btc_data['Vol.'] = btc_data['Vol.'].apply(convert_volume)
    
    # Convert 'Change %' to a float after removing the '%' sign
    btc_data['Change %'] = btc_data['Change %'].str.rstrip('%').astype(float) / 100
    btc_data.sort_index(inplace=True)

    return btc_data

def lump_sum_and_hold_strategy(btc_data, starting_investment):
    # Assuming starting investment is made on the first day of the given data
    initial_price = btc_data['Price'].iloc[0]
    btc_bought = starting_investment / initial_price
    portfolio_value = btc_bought * btc_data['Price']
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
            btc_owned += monthly_investment / btc_data['Price'].iloc[i]
        
        # Update portfolio value for the current day
        portfolio_value.iloc[i] = btc_owned * btc_data['Price'].iloc[i]
    
    portfolio_value.iloc[0] = 0  # Start with a 0 investment
    portfolio_value.ffill(inplace=True)  # Forward fill the portfolio value for days without transactions

    return portfolio_value
# Function to execute trading strategy
def execute_strategy(btc_data, starting_investment, start_date, buying_rule, selling_rule):
    if pd.to_datetime(start_date) not in btc_data.index:
        raise ValueError("Start date is out of the dataset's date range.")

    # Filter the data to start from the given start date
    btc_data = btc_data[start_date:]
    
    available_cash = starting_investment
    btc_owned = 0
    transactions = []
    portfolio_value_over_time = pd.Series(index=btc_data.index, dtype=float)

    for i in range(len(btc_data)):
        current_data = btc_data.iloc[:i+1]
        current_price = current_data['Price'].iloc[-1]
        date = current_data.index[-1]

        # Calculate current portfolio value (BTC holdings + cash)
        current_portfolio_value = btc_owned * current_price + available_cash
        portfolio_value_over_time[date] = current_portfolio_value

        # Prepare the context
        context = {
            'last_highest': lambda col: ta.utils.max_since_start(current_data[col]),
            'last_lowest': lambda col: ta.utils.min_since_start(current_data[col]),
            'moving_average': lambda col, window=3: ta.trend.sma(current_data[col], window=window).iloc[-1],
            'current': lambda col: current_data[col].iloc[-1],
            'available_cash': available_cash,
            'btc_owned': btc_owned,
            'price': current_price,
            'rsi': lambda window=14: ta.momentum.rsi(current_data['Price'].values, window=window),
            'macd': lambda fast=12, slow=26, signal=9: ta.trend.macd(current_data['Price'].values, fast=fast, slow=slow, signal=signal),
            'bollinger_bands': lambda window=20, num_std=2: ta.volatility.bollinger_bands(current_data['Price'].values, window=window, std=num_std),
            'ema': lambda window=20: ta.trend.ema_indicator(current_data['Price'].values, window=window),
            'stochastic_oscillator': lambda k_window=14, d_window=3: ta.momentum.stoch(current_data['High'].values, current_data['Low'].values, current_data['Price'].values, k_window=k_window, d_window=d_window),
            'average_true_range': lambda window=14: ta.volatility.average_true_range(current_data['High'].values, current_data['Low'].values, current_data['Price'].values, window=window),
            'on_balance_volume': lambda: ta.volume.on_balance_volume(current_data['Price'].values, current_data['Vol.'].values),
            'momentum': lambda window=14: ta.momentum.momentum(current_data['Price'].values, window=window),
            'roi': lambda entry_price, exit_price: (exit_price - entry_price) / entry_price * 100,
            'stop_loss': lambda entry_price, percentage=10: entry_price - entry_price * (percentage / 100),
            'take_profit': lambda entry_price, percentage=20: entry_price + entry_price * (percentage / 100),
            'percent_change': lambda periods=1: current_data['Price'].pct_change(periods=periods).iloc[-1],
            'volatility': lambda window=20: ta.volatility.average_true_range(current_data['High'].values, current_data['Low'].values, current_data['Price'].values, window=window).mean(),
            'atr_percent': lambda window=14: ta.volatility.average_true_range_percent(current_data['High'].values, current_data['Low'].values, current_data['Price'].values, window=window).iloc[-1],
            'ichimoku_cloud': lambda conversion_window=9, base_window=26, lagging_window=52: ta.trend.ichimoku_cloud(current_data['High'].values, current_data['Low'].values, conversion_window=conversion_window, base_window=base_window, lagging_window=lagging_window),
            'parabolic_sar': lambda af=0.02, max_af=0.2: ta.trend.psar(current_data['High'].values, current_data['Low'].values, current_data['Price'].values, af=af, max_af=max_af),
            'support_resistance': lambda window=20: ta.resistance_support(current_data['Price'].values, window=window),
            'volume_spike': lambda window=20, threshold=2: ta.volume.volume_spike_detection(current_data['Vol.'].values, window=window, threshold=threshold),
            'price_pattern': lambda pattern='double_top': ta.pattern.find_pattern(current_data['Price'].values, pattern=pattern),
            'fibonacci_retracement': lambda start, end: ta.fibonacci.fibonacci_retracement(current_data['Price'].values, start, end),
            'days_since_last_halving': lambda: days_since_last_halving(current_data.index[-1]),
            'power_law': lambda start_date, end_date: power_law(current_data, start_date, end_date),
            'price_power_law_relation': lambda start_date, end_date: price_power_law_relation(current_data, start_date, end_date)
        }

        try:
            buy_eval = eval(buying_rule, {"__builtins__": None}, context)
            sell_eval = eval(selling_rule, {"__builtins__": None}, context)
        except Exception as e:
            print(f"Error evaluating rules: {e}")
            continue

        date = current_data.index[-1]

        if buy_eval and available_cash >= current_price:
            btc_to_buy = available_cash // current_price
            available_cash -= btc_to_buy * current_price
            btc_owned += btc_to_buy
            transactions.append({'Date': date, 'Action': 'Buy', 'BTC': btc_to_buy, 'Price': current_price, 'Owned Cash': round(available_cash, 2), 'Owned BTC': btc_owned})

        elif sell_eval and btc_owned > 0:
            btc_to_sell = btc_owned
            available_cash += btc_to_sell * current_price
            btc_owned -= btc_to_sell
            transactions.append({'Date': date, 'Action': 'Sell', 'BTC': btc_to_sell, 'Price': current_price, 'Owned Cash': round(available_cash, 2), 'Owned BTC': btc_owned})

    transactions_df = pd.DataFrame(transactions)

    return transactions_df, portfolio_value_over_time

layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            # dbc.CardHeader(html.H3("Backtesting Parameters")),
                            dbc.CardBody([
                                    dbc.Row(
                                        [
                                            dbc.Label("Starting Investment", html_for="input-starting-investment", width=12),
                                            dbc.Col(
                                                dcc.Input(id="input-starting-investment", type="number", value=10000),
                                                width=12,
                                            ),
                                        ]
                                    ),
                                    dbc.Row(
                                        [
                                            dbc.Label("Starting Date", html_for="input-starting-date", width=12),
                                            dbc.Col(
                                                dcc.DatePickerSingle(id="input-starting-date", date='2020-01-01'),
                                                width=12,
                                            ),
                                        ]
                                    ),
                                    dbc.Row(
                                        [
                                            dbc.Col(dbc.Label("Buying Rule (Python expression)"), width=12),
                                        ]
                                    ),
                                    dbc.Row(
                                        [
                                            dbc.Col(dcc.Textarea(id="input-buying-rule", value="available_cash > 1000 and price < 50000", placeholder="Buying Rule"), width=8),
                                            dbc.Col(create_rule_generation_button(1), width=3),
                                        ]
                                    ),
                                    dbc.Row(
                                        [
                                            dbc.Col(dbc.Label("Selling Rule (Python expression)"), width=12),
                                        ]
                                    ),
                                    dbc.Row(
                                        [
                                            dbc.Col(dcc.Textarea(id="input-selling-rule", value="btc_owned > 0 and price > 60000", placeholder="Selling Rule"), width=8),
                                            dbc.Col(create_rule_generation_button(2), width=3),  # Reused button
                                        ]
                                    ),
                                    rule_generation_modal,
                                    dbc.Row(
                                        [
                                            dbc.Label("", html_for="scale-toggle", width=12),
                                            dbc.Col(
                                                dbc.RadioItems(
                                                    options=[
                                                        {"label": "Log Scale", "value": "log"},
                                                        {"label": "Normal Scale", "value": "linear"},
                                                    ],
                                                    value="log",
                                                    id="scale-toggle"
                                                ),
                                                width=12, align="center",
                                            ),
                                        ]
                                    ),
                                ]
                            ),
                        ]
                    ),
                    sm=12, md=4
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardBody(
                                [
                                    dcc.Graph(id='backtesting-graph'),
                                    dash_table.DataTable(
                                        id='backtesting-table',
                                        style_table={'height': '400px', 'overflowY': 'auto'},
                                        style_cell={'textAlign': 'left'},
                                    )
                                ]
                            ),
                        ]
                    ),
                    sm=12, md=8
                ),
            ]
        )
    ],
    fluid=True,
)

def register_callbacks(app):
    @app.callback(
        [Output('backtesting-table', 'data'),
         Output('backtesting-table', 'columns'),
         Output('backtesting-graph', 'figure')],
        [Input('input-starting-investment', 'value'),
         Input('input-starting-date', 'date'),
         Input('input-buying-rule', 'value'),
         Input('input-selling-rule', 'value'),
         Input('scale-toggle', 'value')]
    )
    def update_backtesting(starting_investment, start_date, buying_rule, selling_rule, scale):
        if None in [starting_investment, start_date, buying_rule, selling_rule]:
            raise PreventUpdate

        btc_data = fetch_historical_data('./btc_hist_prices.csv')  # Load the entire historical dataset
        transactions_df, portfolio_value_over_time = execute_strategy(btc_data, starting_investment, start_date, buying_rule, selling_rule)

        # Calculate strategies
        lump_sum_portfolio = lump_sum_and_hold_strategy(btc_data[start_date:], starting_investment)
        dca_portfolio = monthly_dca_strategy(btc_data[start_date:], starting_investment)  # Total Invest / Months

        # Plotting
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:]['Price'], mode='lines', name='BTC Price'))
        fig.add_trace(go.Scatter(x=lump_sum_portfolio.index, y=lump_sum_portfolio, mode='lines', name='Lump Sum & Hold Portfolio'))
        fig.add_trace(go.Scatter(x=dca_portfolio.index, y=dca_portfolio, mode='lines', name='Monthly DCA Portfolio'))
        fig.add_trace(go.Scatter(x=portfolio_value_over_time.index, y=portfolio_value_over_time, mode='lines', name='Portfolio Value'))

        # Highlight transactions if available
        if not transactions_df.empty:
            buy_transactions = transactions_df[transactions_df['Action'] == 'Buy']
            sell_transactions = transactions_df[transactions_df['Action'] == 'Sell']
            if not buy_transactions.empty:
                fig.add_trace(go.Scatter(x=buy_transactions['Date'], y=buy_transactions['Price'], mode='markers', name='Buy', marker=dict(color='green', size=10)))
            if not sell_transactions.empty:
                fig.add_trace(go.Scatter(x=sell_transactions['Date'], y=sell_transactions['Price'], mode='markers', name='Sell', marker=dict(color='red', size=10)))

        # Update the layout
        fig.update_layout(title='Backtesting Results Over Time', xaxis_title='Date', yaxis_title='Portfolio Value', legend_title='Strategy', transition_duration=500)

        table_data = transactions_df.to_dict('records')
        table_columns = [{"name": i, "id": i} for i in transactions_df.columns]

        fig.update_yaxes(type=scale)

        return table_data, table_columns, fig
