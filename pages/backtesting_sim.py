import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table, ctx
from dash.dependencies import Input, Output, State, ALL
import pandas as pd
import numpy as np
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import ta
import os
from core.utils import *
import yfinance as yf

from pathlib import Path
from core.conf import *

from components.gpt_functionality import context_description

# Function to fetch historical data for Bitcoin
def convert_volume(value):
    if isinstance(value, str):
        value = value.replace(',', '').upper()  # Remove commas and standardize to uppercase
        if 'K' in value:
            return float(value.replace('K', '')) * 1e3
        elif 'M' in value:
            return float(value.replace('M', '')) * 1e6
        elif 'B' in value:
            return float(value.replace('B', '')) * 1e9
    return pd.to_numeric(value, errors='coerce')  # Convert safely if the value is numeric
    
def fetch_historical_data(csv_file_path):
    # Load data from CSV
    btc_data_raw = pd.read_csv(csv_file_path, parse_dates=['Date'], index_col='Date', dtype={'Vol.': str})
    btc_data_raw.sort_index(inplace=True)

    # Clean up numeric columns in btc_data_raw (remove commas and convert to float)
    btc_data_raw['Price'] = btc_data_raw['Price'].str.replace(',', '').astype(float)
    btc_data_raw['Open'] = btc_data_raw['Open'].str.replace(',', '').astype(float)
    btc_data_raw['High'] = btc_data_raw['High'].str.replace(',', '').astype(float)
    btc_data_raw['Low'] = btc_data_raw['Low'].str.replace(',', '').astype(float)
    btc_data_raw['Vol.'] = btc_data_raw['Vol.'].apply(convert_volume)
    
    # Convert 'Change %' to numeric by removing '%' and converting to float
    btc_data_raw['Change %'] = btc_data_raw['Change %'].str.replace('%', '').astype(float)

    # Download recent data from Yahoo Finance
    btc_data_yahoo = yf.download('BTC-USD', start=btc_data_raw.index[-1] + pd.to_timedelta(1, unit='D'), progress=False)

    # If Yahoo data is empty, just use the CSV data
    if btc_data_yahoo.empty:
        return btc_data_raw

    # Adjust Yahoo data to match your CSV format
    btc_data_yahoo.reset_index(inplace=True)
    btc_data_yahoo.rename(columns={
        'Date': 'Date',
        'Adj Close': 'Price',
        'Open': 'Open',
        'High': 'High',
        'Low': 'Low',
        'Volume': 'Vol.'
    }, inplace=True)

    btc_data_yahoo.set_index('Date', inplace=True)

    # Remove unnecessary columns and ensure consistency with historical data
    btc_data_yahoo = btc_data_yahoo[['Price', 'Open', 'High', 'Low', 'Vol.']]

    # Convert Yahoo data columns to appropriate types
    btc_data_yahoo['Price'] = btc_data_yahoo['Price'].astype(float)
    btc_data_yahoo['Open'] = btc_data_yahoo['Open'].astype(float)
    btc_data_yahoo['High'] = btc_data_yahoo['High'].astype(float)
    btc_data_yahoo['Low'] = btc_data_yahoo['Low'].astype(float)
    btc_data_yahoo['Vol.'] = btc_data_yahoo['Vol.'].astype(float)

    # Concatenate the historical and Yahoo data
    btc_data_combined = pd.concat([btc_data_raw, btc_data_yahoo])

    # Sort the index to maintain chronological order
    btc_data_combined.sort_index(inplace=True)

    # Rename 'Vol.' to 'volume' for consistency
    btc_data_combined.rename(columns={'Vol.': 'volume'}, inplace=True)

    # Fill missing values if there are any gaps
    btc_data_combined.ffill(inplace=True)

    return btc_data_combined

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

def add_oscillators_quantiles(btc_data):
    # Filter columns with "oscillator" in the name
    oscillator_columns = btc_data.filter(like='oscillator')

    # Normalize these columns to range 0:1
    normalized_oscillators = oscillator_columns.apply(lambda x: (x - x.min()) / (x.max() - x.min()))
    # plt.figure(figsize=(10, 8))
    # sns.heatmap(normalized_oscillators, cmap="YlGnBu", cbar_kws={'label': 'Normalized Value'})
    # plt.show()

    # Calculate new columns as specified quantiles
    btc_data['1st_quantile_oscillators'] = normalized_oscillators.quantile(0.01, axis=1)
    btc_data['4th_quantile_oscillators'] = normalized_oscillators.quantile(0.25, axis=1)
    btc_data['50th_quantile_oscillators'] = normalized_oscillators.quantile(0.5, axis=1)
    btc_data['96th_quantile_oscillators'] = normalized_oscillators.quantile(0.96, axis=1)
    btc_data['99th_quantile_oscillators'] = normalized_oscillators.quantile(0.99, axis=1)

    return btc_data

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
def execute_strategy(btc_data, starting_investment, start_invested, start_date, buying_rule, selling_rule, trade_amount, transaction_fee, taxation_method, tax_amount, holding_period):
    if pd.to_datetime(start_date) not in btc_data.index:
        start_date = btc_data.index[0].strftime('%Y-%m-%d')
        print("Start date is out of the dataset's date range.")

    # Filter the data to start from the given start date
    btc_data = btc_data[start_date:]

    print(start_invested, "invested at", start_date)
    if start_invested:
        print("Starting with an initial investment of", starting_investment)
        available_cash = 0
        btc_owned = starting_investment / btc_data.iloc[0]['price']
    else:
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
            print(f"Error on date {date.strftime('%Y-%m-%d')}:")
            print(f"Current price: {context['current']('price')}")
            print(f"Historical prices: {context['historic']('price')[-5:]}")  # Print last 5 prices for context
            if not sell_eval:
                print(f"Sell Rule could not be applied to this day: {e} >>> {selling_rule}")
            if not buy_eval:
                print(f"Buy Rule could not be applied to this day: {e} >>> {buying_rule}")
            continue

        if buy_eval and available_cash > 0:
            # Calculate the maximum number of BTC that can be bought with available cash
            max_btc_to_buy = (available_cash - transaction_fee) / current_price
            
            # Buy the lesser of trade_amount or max_btc_to_buy
            if max_btc_to_buy > 0:
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
                total_gain = 0
                for i in range(int(btc_to_sell)):
                    if btc_purchases:
                        purchase = btc_purchases.pop(0)
                        gain = (current_price - purchase["price"]) * (1 / btc_to_sell)  # Calculate gain proportionally
                        purchase_date = pd.to_datetime(purchase["date"])  # Convert string to Timestamp
                        current_holding_period = (date - purchase_date).days
                        if current_holding_period <= holding_period:
                            total_gain += gain  # Accumulate the gains portion for taxable calculation
                
                taxable_amount = total_gain * (tax_amount / 100)  # Tax on only the gain portion

            available_cash += sale_proceeds - taxable_amount - transaction_fee
            btc_owned -= btc_to_sell
            transactions.append({
                'Date': date.strftime('%Y-%m-%d'),
                'Action': 'SELL',
                'BTC': round(btc_to_sell, 12),
                'price': current_price,
                'Owned Cash': round(available_cash, 2),
                'Owned BTC': round(btc_owned, 12),
                'Taxable Amount': round(taxable_amount, 2)
            })

    transactions_df = pd.DataFrame(transactions)

    return transactions_df, portfolio_value_over_time


loading_component = dbc.Spinner(color="primary", children="Running Backtest...")

# Import rule builder components
from components.rule_builder import (
    create_rule_builder_card, ai_rule_modal, info_modal, 
    save_rules_modal, load_rules_modal, get_rules_from_ui
)

layout = dbc.Container([
    # Page Header
    html.Div([
        html.H4([
            html.I(className="bi bi-graph-up me-2"),
            "Backtesting"
        ], className="page-title"),
        html.P("Test trading strategies against historical data", className="page-subtitle"),
    ], className="page-header"),
    
    dbc.Row([
        # Left Panel - Parameters & Rules
        dbc.Col([
            # Asset Selection Card
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-coin me-2"),
                    "Asset"
                ], className="card-header-modern"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Button("Bitcoin", id="asset-btc-btn", color="primary", size="sm", className="me-1 asset-type-tab active"),
                                dbc.Button("Stock/ETF", id="asset-stock-btn", color="link", size="sm", className="asset-type-tab"),
                            ], className="asset-type-tabs mb-2"),
                            dbc.Input(
                                id="asset-symbol-input",
                                type="text",
                                placeholder="e.g. AAPL, SPY, MSFT",
                                className="compact-input",
                                style={"display": "none"}
                            ),
                            dcc.Store(id="selected-asset", data="BTC-USD"),
                        ], width=12),
                    ]),
                ], className="py-2"),
            ], className="card-modern mb-2"),
            
            # Parameters Card (Compact)
            dbc.Card([
                dbc.CardHeader([
                    html.Div([
                        html.I(className="bi bi-sliders me-2"),
                        html.Span("Parameters"),
                    ], className="d-flex align-items-center"),
                    dbc.Button(
                        html.I(className="bi bi-chevron-down", id="collapse-icon"),
                        id="collapse-button",
                        color="link",
                        size="sm",
                        className="ms-auto p-0"
                    ),
                ], className="card-header-modern d-flex justify-content-between"),
                dbc.Collapse([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Cash ($)", className="input-label"),
                                dbc.Input(
                                    id="input-starting-investment",
                                    type="number",
                                    value=10000,
                                    className="compact-input"
                                ),
                            ], width=6),
                            dbc.Col([
                                dbc.Label("Trade Size ($)", className="input-label"),
                                dbc.Input(
                                    id="input-trade-amount",
                                    type="number",
                                    value=100,
                                    className="compact-input"
                                ),
                            ], width=6),
                        ], className="mb-2"),
                        
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Fee ($)", className="input-label"),
                                dbc.Input(
                                    id="input-transaction-fee",
                                    type="number",
                                    value=0.01,
                                    step=0.01,
                                    className="compact-input"
                                ),
                            ], width=6),
                            dbc.Col([
                                dbc.Label("Tax (%)", className="input-label"),
                                dbc.Input(
                                    id="input-tax-amount",
                                    type="number",
                                    value=25,
                                    min=0, max=100,
                                    className="compact-input"
                                ),
                            ], width=6),
                        ], className="mb-2"),
                        
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Start Date", className="input-label"),
                                dcc.DatePickerSingle(
                                    id="input-starting-date",
                                    date='2018-01-01',
                                    display_format="DD/MM/YYYY",
                                    className="compact-date"
                                ),
                            ], width=6),
                            dbc.Col([
                                dbc.Label("Tax Method", className="input-label"),
                                dcc.Dropdown(
                                    id="taxation-method-dropdown",
                                    options=[{"label": "FIFO", "value": "FIFO"}],
                                    value="FIFO",
                                    clearable=False,
                                    className="compact-dropdown"
                                ),
                            ], width=6),
                        ], className="mb-2"),
                        
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Hold Period (days)", className="input-label"),
                                dbc.Input(
                                    id="input-holding-period",
                                    type="number",
                                    value=365,
                                    className="compact-input"
                                ),
                            ], width=6),
                            dbc.Col([
                                html.Div([
                                    dbc.Checkbox(
                                        id='start-invested',
                                        value=False,
                                        className="me-2"
                                    ),
                                    html.Label("Start fully invested", className="form-check-label", style={"fontSize": "0.75rem", "marginTop": "0"}),
                                ], className="d-flex align-items-center", style={"paddingTop": "20px"}),
                            ], width=6),
                        ]),
                    ], className="compact-form"),
                ], id="collapse", is_open=True),
            ], className="card-modern mb-3"),
            
            # Rule Builder
            create_rule_builder_card(),
            
            # Modals
            ai_rule_modal,
            info_modal,
            save_rules_modal,
            load_rules_modal,
            dcc.Store(id="saved-rules-store", storage_type="local"),
            
        ], md=4, className="mb-3"),
        
        # Right Panel - Chart & Results
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dcc.Loading(
                        id="loading-graph",
                        type="circle",
                        children=dcc.Graph(id='backtesting-graph', className="chart-container"),
                    ),
                ]),
            ], className="card-modern mb-3"),
            
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-list-ul me-2"),
                    "Transaction History"
                ], className="card-header-modern"),
                dbc.CardBody([
                    dcc.Loading(
                        id="loading-table",
                        type="circle",
                        children=dash_table.DataTable(
                            id='backtesting-table',
                            style_table={'height': '300px', 'overflowY': 'auto'},
                            style_cell={'textAlign': 'left', 'padding': '8px', 'fontFamily': 'Inter, sans-serif', 'fontSize': '0.85rem'},
                            style_header={'fontWeight': '600', 'backgroundColor': '#f8fafc'},
                        )
                    )
                ]),
            ], className="card-modern"),
        ], md=8),
    ]),
], fluid=True)

def register_callbacks(app):
    # Asset picker callbacks
    @app.callback(
        [Output("asset-btc-btn", "className"),
         Output("asset-stock-btn", "className"),
         Output("asset-symbol-input", "style"),
         Output("selected-asset", "data")],
        [Input("asset-btc-btn", "n_clicks"),
         Input("asset-stock-btn", "n_clicks"),
         Input("asset-symbol-input", "value")],
        [State("selected-asset", "data")],
        prevent_initial_call=True
    )
    def toggle_asset_type(btc_clicks, stock_clicks, symbol_input, current_asset):
        from dash import ctx
        triggered = ctx.triggered_id
        
        if triggered == "asset-btc-btn":
            return "me-1 asset-type-tab active", "asset-type-tab", {"display": "none"}, "BTC-USD"
        elif triggered == "asset-stock-btn":
            return "me-1 asset-type-tab", "asset-type-tab active", {"display": "block"}, symbol_input or "AAPL"
        elif triggered == "asset-symbol-input" and symbol_input:
            return "me-1 asset-type-tab", "asset-type-tab active", {"display": "block"}, symbol_input.upper()
        
        return "me-1 asset-type-tab active", "asset-type-tab", {"display": "none"}, current_asset or "BTC-USD"
    
    @app.callback(
        [Output('backtesting-table', 'data'),
         Output('backtesting-table', 'columns'),
         Output('backtesting-graph', 'figure')],
        [Input('update-backtesting-button', 'n_clicks')],
        [State('input-starting-investment', 'value'),
         State('start-invested', 'value'),
        State('input-starting-date', 'date'),
        State("trading-rules-container", "children"),
        State("saved-rules-store", "data"),
        State('scale-toggle', 'value'),
        State('input-trade-amount', 'value'),
        State('input-transaction-fee', 'value'),
        State('taxation-method-dropdown', 'value'),
        State('input-tax-amount', 'value'),
        State('input-holding-period', 'value'),
        State('selected-asset', 'data')]
    )
    def update_backtesting(n_clicks, starting_investment, start_invested, start_date, children, store_data, scale, trade_amount, transaction_fee, taxation_method, tax_amount, holding_period, selected_asset):
        if None in [starting_investment, start_date, children]:
            raise PreventUpdate
        
        if store_data:
            rules_from_ui = get_rules_from_ui(children)
            buying_rule = " or ".join(rules_from_ui.get("buying_rule", []))
            selling_rule = " or ".join(rules_from_ui.get("selling_rule", []))

        if not os.path.exists(PREPROC_FILENAME) or PREPROC_OVERWRITE:
            print(f"Reloading all historical data.")

            try:
                # Load historical dataset
                btc_data = fetch_historical_data('./btc_hist_prices.csv')
                if btc_data.empty:
                    raise ValueError("Historical BTC data is empty after loading. Please check the source CSV.")

                # Convert all column names to lowercase for consistency
                btc_data.columns = btc_data.columns.str.lower()
                
                print("Loaded historical data (sample):")
                print(btc_data.head())  # Print just the first few rows for sanity check
                
                # Add historical indicators to BTC data
                btc_data = add_historical_indicators(btc_data)
                print("Added historical indicators.")

                # Add on-chain data
                try:
                    onchain_data = fetch_onchain_indicators('./indicators')
                    if onchain_data.empty:
                        print("Warning: On-chain data is empty. Proceeding without it.")
                    else:
                        print("Loaded on-chain data (sample):")
                        print(onchain_data.head())

                    # Ensure on-chain data column names are also lowercase for consistency
                    onchain_data.columns = onchain_data.columns.str.lower()
                    
                    # Merge BTC and on-chain data
                    btc_data_full = btc_data.join(onchain_data, how='left')
                    print("Merged historical BTC data with on-chain data.")
                except FileNotFoundError as e:
                    print(f"Error: On-chain indicators directory not found: {e}")
                    btc_data_full = btc_data  # Proceed with only historical BTC data if on-chain data is unavailable

                # Add oscillators quantiles to the combined data
                btc_data_full = add_oscillators_quantiles(btc_data_full)
                print("Added oscillators quantiles.")

                # Write the preprocessed data to CSV, explicitly fail if any issue occurs
                try:
                    btc_data_full.to_csv(PREPROC_FILENAME)
                    print(f"Data saved to {PREPROC_FILENAME}.")
                except Exception as e:
                    raise RuntimeError(f"Failed to save data to {PREPROC_FILENAME}: {e}")

            except Exception as e:
                print(f"An unexpected error occurred: {e}")

        else:
            btc_data = pd.read_csv(PREPROC_FILENAME, parse_dates=['Date'], index_col='Date')
            print(f"Data loaded from {PREPROC_FILENAME}.")
        
        transactions_df, portfolio_value_over_time = execute_strategy(btc_data, starting_investment, start_invested, start_date, buying_rule, selling_rule, trade_amount, transaction_fee, taxation_method, tax_amount, holding_period)

        # Calculate strategies
        lump_sum_portfolio = lump_sum_and_hold_strategy(btc_data[start_date:], starting_investment)
        dca_portfolio = monthly_dca_strategy(btc_data[start_date:], starting_investment)  # Total Invest / Months

        # Plotting
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:]['price'], mode='lines', name='BTC price'))
        fig.add_trace(go.Scatter(x=lump_sum_portfolio.index, y=lump_sum_portfolio, mode='lines', name='Lump Sum & Hold Portfolio'))
        fig.add_trace(go.Scatter(x=dca_portfolio.index, y=dca_portfolio, mode='lines', name='Monthly DCA Portfolio'))
        fig.add_trace(go.Scatter(x=portfolio_value_over_time.index, y=portfolio_value_over_time, mode='lines', name='Portfolio Value'))
        
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
            yaxis2=dict(
                title="Indicators",
                overlaying='y',
                side='right',
                showgrid=False,  # Disable gridlines for clarity
                automargin=True  # Automatically adjust margins to fit the axis
            )
        )
        
        # Dynamically add traces mentioned in buy and sell rules
        columns_to_plot = extract_columns_from_expression([buying_rule, selling_rule])
        for column in columns_to_plot:
            if column in btc_data.columns and column != 'price':
                fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:][column], mode='lines', name=column, visible='legendonly', yaxis='y2'))

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
        [Output("collapse", "is_open"), Output("collapse-icon", "className")],
        [Input("collapse-button", "n_clicks")],
        [State("collapse", "is_open")],
    )
    def toggle_collapse(n, is_open):
        if n:
            new_class = "bi bi-chevron-up" if not is_open else "bi bi-chevron-down"
            return not is_open, new_class
        return is_open, "bi bi-chevron-down"