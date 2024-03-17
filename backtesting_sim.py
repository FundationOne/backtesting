import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table, ctx
from dash.dependencies import Input, Output, State, ALL
import pandas as pd
import numpy as np
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import ta
import os
import json
from utils import *

from dash.exceptions import PreventUpdate
from openai import OpenAI
from conf import *

from gpt_functionality import create_rule_generation_button,  rule_generation_modal, generate_rule

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

def add_historical_indicators(btc_data):
    btc_data['last_highest'] = btc_data['price'].cummax()
    btc_data['last_lowest'] = btc_data['price'].cummin()
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
def execute_strategy(btc_data, starting_investment, start_date, buying_rule, selling_rule):
    if pd.to_datetime(start_date) not in btc_data.index:
        start_date = btc_data.index[0].strftime('%Y-%m-%d')
        print("Start date is out of the dataset's date range.")

    # Filter the data to start from the given start date
    btc_data = btc_data[start_date:]

    available_cash = starting_investment
    btc_owned = 0
    transactions = []
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

        if buy_eval and available_cash >= current_price:
            btc_to_buy = available_cash // current_price
            available_cash -= btc_to_buy * current_price
            btc_owned += btc_to_buy
            transactions.append({'Date': date, 'Action': 'Buy', 'BTC': btc_to_buy, 'price': current_price, 'Owned Cash': round(available_cash, 2), 'Owned BTC': btc_owned})

        elif sell_eval and btc_owned > 0:
            btc_to_sell = btc_owned
            available_cash += btc_to_sell * current_price
            btc_owned -= btc_to_sell
            transactions.append({'Date': date, 'Action': 'Sell', 'BTC': btc_to_sell, 'price': current_price, 'Owned Cash': round(available_cash, 2), 'Owned BTC': btc_owned})

    transactions_df = pd.DataFrame(transactions)

    return transactions_df, portfolio_value_over_time


def create_rule_input(rule_type, rule_values, rule_expression):
    type_label = html.Div(rule_type.capitalize(), style={
        "writingMode": "vertical-lr",
        "marginRight": "5px",
        "color": "#555"
    })

    input_field = dcc.Textarea(
        id={"type": f"{rule_type}-rule", "index": len(rule_values)},
        value=rule_expression,
        rows=2,
        style={"width": "90%", "fontSize":"14px"},
    )

    remove_button = dbc.Button(
        children="➖",
        id={"type": f"remove-rule", "index": len(rule_values)},
        n_clicks=0,
        style={"padding": "0.25rem 0.5rem", "border": "none", "backgroundColor": "transparent"},
    )
    return dbc.ListGroupItem(
        [type_label, input_field, remove_button],
        style={"display": "flex", "alignItems": "center"}
    )

def get_rules_from_input(children):
    rules = {
        "buying-rule": [],
        "selling-rule": []
    }

    for child in children:
        textarea = child['props']['children'][1]  # Textarea is the second child
        textarea_props = textarea['props']
        rule_type = textarea_props['id']['type']
        rule_value = textarea_props['value'].strip()

        # Append rule_value to the appropriate list based on rule_type
        if rule_type == "buy-rule" and rule_value:
            rules["buying-rule"].append(rule_value)
        elif rule_type == "sell-rule" and rule_value:
             rules["selling-rule"].append(rule_value)

    buying_rule = " or ".join(rules["buying-rule"])
    selling_rule = " or ".join(rules["selling-rule"])

    return buying_rule, selling_rule

loading_component = dbc.Spinner(color="primary", children="Running Backtest...")
predefined_rules = ["current('price') < current('power_law_price_4y_window')"]

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
                                                dcc.Input(id="input-starting-investment", type="number", value=1000),
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
                                            dbc.Col(dbc.Label("Buy/Sell Rules\n(Python Expressions)"), width=8),
                                            dbc.Col(dbc.Label(create_rule_generation_button(1)), width=4),
                                            rule_generation_modal
                                        ]
                                    ),

                                    html.Div(
                                        id="trading-rules-container",
                                        children=[
                                            create_rule_input("buy", range(len(predefined_rules)), rule)
                                            for i, rule in enumerate(predefined_rules)
                                        ],
                                    ),
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
                                    dbc.Row(
                                        dbc.Col(
                                            dbc.Button("Run Backtest", id="update-backtesting-button", className="me-2", n_clicks=0),
                                            width={"size": 6, "offset": 3},
                                        ),
                                        className="mb-3",
                                    )
                                ]
                            ),
                        ], style={"border":"unset"}
                    ),
                    sm=12, md=4
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
        [Input('update-backtesting-button', 'n_clicks')],  # Updated trigger
        [State('input-starting-investment', 'value'),
        State('input-starting-date', 'date'),
        State("trading-rules-container", "children"),
        State('scale-toggle', 'value')]
    )
    def update_backtesting(n_clicks, starting_investment, start_date, children, scale):
        if None in [starting_investment, start_date, children]:
            raise PreventUpdate
        
        buying_rule, selling_rule = get_rules_from_input(children)

        if not os.path.exists(PREPROC_FILENAME) or PREPROC_OVERWRITE:
            btc_data = fetch_historical_data('./btc_hist_prices.csv')  # Load the entire historical dataset
            btc_data = add_historical_indicators(btc_data)
            btc_data.to_csv(PREPROC_FILENAME)
            print(f"Data saved to {PREPROC_FILENAME}.")
        else:
            btc_data = pd.read_csv(PREPROC_FILENAME, parse_dates=['Date'], index_col='Date')
            print(f"Data loaded from {PREPROC_FILENAME}.")

        transactions_df, portfolio_value_over_time = execute_strategy(btc_data, starting_investment, start_date, buying_rule, selling_rule)

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

        # fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:]['power_law_price'], mode='lines', name='BTC Power Law', visible='legendonly'))
        # fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:]['power_law_price_1y_window'], mode='lines', name='BTC Power Law 1Y Window', visible='legendonly'))
        # fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:]['power_law_price_4y_window'], mode='lines', name='BTC Power Law 4Y Window', visible='legendonly'))
        # fig.add_trace(go.Scatter(x=btc_data[0:].index, y=btc_data[0:]['sma_20_week'], mode='lines', name='BTC 20 Week SMA', visible='legendonly'))

        # highlight transactions if available
        if not transactions_df.empty:
            buy_transactions = transactions_df[transactions_df['Action'] == 'Buy']
            sell_transactions = transactions_df[transactions_df['Action'] == 'Sell']
            if not buy_transactions.empty:
                fig.add_trace(go.Scatter(x=buy_transactions['Date'], y=buy_transactions['price'], mode='markers', name='Buy', marker=dict(color='green', size=10)))
            if not sell_transactions.empty:
                fig.add_trace(go.Scatter(x=sell_transactions['Date'], y=sell_transactions['price'], mode='markers', name='Sell', marker=dict(color='red', size=10)))

        # Update the layout
        fig.update_layout(title='Backtesting Results Over Time', xaxis_title='Date', yaxis_title='Portfolio Value', legend_title='Strategy', transition_duration=500)

        table_data = transactions_df.to_dict('records')
        table_columns = [{"name": i, "id": i} for i in transactions_df.columns]

        fig.update_yaxes(type=scale)

        return table_data, table_columns, fig
  
    @app.callback(
        [Output("trading-rules-container", "children"),
        Output("rule-generation-modal", "is_open")],
        [Input({'type': 'generate-rule-button', 'index': ALL}, 'n_clicks'),
        Input({"type": "remove-rule", "index": ALL}, "n_clicks"),
        Input("apply-modal-button", "n_clicks"),
        Input("close-modal-button", "n_clicks")],
        [State("trading-rules-container", "children"),
        State({"type": "buying-rule", "index": ALL}, "value"),
        State("input-generate-rule", "value"),
        State("input-openai-api-key", "value"),
        State("rule-generation-modal", "is_open")],
        prevent_initial_call=True
    )
    def generate_rules(generate_rule_clicks, remove_clicks, apply_modal_click, close_modal_click, children, rule_values, rule_instruction, openai_api_key, is_modal_open):
        trigger_id = ctx.triggered[0]["prop_id"] if ctx.triggered else None
        try:
            button_clicked = json.loads(trigger_id.split(".")[0]) if trigger_id else None
        except Exception as e:
            button_clicked = None

        if button_clicked and button_clicked.get("type") == "generate-rule-button":
            return children, True  # Open the modal

        elif trigger_id == "apply-modal-button.n_clicks":
            if not rule_instruction:
                return children, is_modal_open
            
            rule_expression, rule_type = generate_rule(rule_instruction, openai_api_key)
            children.append(create_rule_input(rule_type, rule_values, rule_expression))

            return children, False  # Close the modal after adding the new rule

        elif trigger_id == "close-modal-button.n_clicks":
            return children, False  # Close the modal

        elif trigger_id and "remove-rule" in trigger_id:
            index = json.loads(trigger_id.split(".")[0])["index"] - 1
            children.pop(index)
            return children, is_modal_open

        return children, is_modal_open
