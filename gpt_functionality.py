import dash_bootstrap_components as dbc
from dash import dcc, no_update
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import openai
import json
import os

# Define the cache directory and file path
cache_dir = os.path.join(os.path.expanduser("~"), ".cache")
cache_file = os.path.join(cache_dir, "openai_api_key.txt")

# Function to update or verify the OpenAI API key in the cache
def update_or_verify_api_key(api_key, cache_file):
    if api_key:
        try:
            with open(cache_file, "r") as f:
                current_api_key = f.read().strip()
            if current_api_key != api_key:
                with open(cache_file, "w") as f:
                    f.write(api_key)
        except FileNotFoundError:
            with open(cache_file, "w") as f:
                f.write(api_key)
    openai.api_key = api_key

def get_initial_api_key(cache_dir, cache_file):    
    # Ensure the cache directory exists
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    
    # Attempt to read the API key from the cache file
    initial_api_key = ""
    if os.path.exists(cache_file):
        with open(cache_file, "r") as file:
            initial_api_key = file.read().strip()
    
    return initial_api_key

# Use the function to initialize the API key
initial_api_key = get_initial_api_key(cache_dir, cache_file)

# Upon starting the app, ensure the API key is correctly set in the cache
update_or_verify_api_key(initial_api_key, cache_file)

context_description = """
The context includes the following functions:

last_highest(col): Returns the highest value of the specified column since the start of the data.
last_lowest(col): Returns the lowest value of the specified column since the start of the data.
moving_average(col, window=3): Returns the simple moving average of the specified column for the given window size.
current(col): Returns the current value of the specified column.
rsi(window=14): Returns the Relative Strength Index (RSI) for the given window size.
macd(fast=12, slow=26, signal=9): Returns the Moving Average Convergence/Divergence (MACD) and signal line for the given parameters.
bollinger_bands(window=20, num_std=2): Returns the upper and lower Bollinger Bands for the given window size and number of standard deviations.
ema(window=20): Returns the Exponential Moving Average (EMA) for the given window size.
stochastic_oscillator(k_window=14, d_window=3): Returns the Stochastic Oscillator (%K and %D) for the given window sizes.
average_true_range(window=14): Returns the Average True Range (ATR) for the given window size.
on_balance_volume(): Returns the On-Balance Volume (OBV).
momentum(window=14): Returns the Momentum indicator for the given window size.
roi(entry_price, exit_price): Returns the Return on Investment (ROI) given the entry and exit prices.
stop_loss(entry_price, percentage=10): Returns the stop-loss price given the entry price and a percentage.
take_profit(entry_price, percentage=20): Returns the take-profit price given the entry price and a percentage.
percent_change(periods=1): Returns the percentage change in price over the given number of periods.
volatility(window=20): Returns the volatility of the price data over the given window size.
atr_percent(window=14): Returns the Average True Range Percent (ATR%) for the given window size.
ichimoku_cloud(conversion_window=9, base_window=26, lagging_window=52): Returns the Ichimoku Cloud indicator for the given parameters.
parabolic_sar(af=0.02, max_af=0.2): Returns the Parabolic Stop and Reverse (SAR) indicator for the given parameters.
support_resistance(window=20): Identifies potential support and resistance levels based on historical price data and a window size.
volume_spike(window=20, threshold=2): Identifies significant volume spikes compared to the average volume over the given window size and threshold.
price_pattern(pattern='double_top'): Identifies specific price patterns (e.g., double top, head and shoulders) in the given data.
fibonacci_retracement(start, end): Calculates the Fibonacci retracement levels between the specified start and end points in the data.
days_since_last_halving(): Returns the number of days since the last Bitcoin halving event.
power_law(start_date, end_date): Returns the power law exponent for the given date range.
price_power_law_relation(start_date, end_date): Returns the ratio of the actual prices to the power law prices for the given date range.

Other variables:
available_cash: The amount of cash available for buying Bitcoin.
btc_owned: The amount of Bitcoin currently owned.
price: The current price of Bitcoin.
"""

# OpenAI API key input
openai_api_key_input = dbc.Row([
    dbc.Label("OpenAI API Key", html_for="input-openai-api-key", width=3),
    dbc.Col([
        dcc.Input(id="input-openai-api-key", value=initial_api_key, type="text", placeholder="Enter your OpenAI API key", className="mb-3")
    ], width=9)
])

# Natural language input for rule generation
rule_generation_input = dbc.Row([
    dbc.Label("Generate Rule", html_for="input-generate-rule", width=3),
    dbc.Col([
        dcc.Input(id="input-generate-rule", type="text", value="", placeholder="Enter natural language instruction", className="mb-3")
    ], width=9)
])

# GPT layout
layout = dbc.Container([
    openai_api_key_input,
    rule_generation_input
])

def register_callbacks(app):
    @app.callback(
        [Output('input-buying-rule', 'value'),
        Output('input-selling-rule', 'value')],
        [Input('input-generate-rule', 'value'),
        State('input-openai-api-key', 'value')]
    )
    def generate_rules(rule_instruction, openai_api_key):
        if not rule_instruction or not openai_api_key:
            raise PreventUpdate

        messages = [
            {"role": "system", "content": f"Here is the eval context that you can use: {context_description}"},
            {"role": "user", "content": f"Natural language instruction: {rule_instruction}\n\nGenerate a Python expression for the trading rule and specify whether it is a buying or selling rule. Return your response in a JSON format. Use double quotes for strings. The JSON format should be exactly as follows: {{\"rule\": \"python_expression\", \"type\": \"buy\" or \"sell\"}}. Ensure proper JSON formatting to avoid parsing errors."}
        ]

        try:
            response = openai.chat.completions.create(
                model="gpt-4",
                messages=messages,
                max_tokens=200,
                n=1,
                stop=None,
                temperature=0.7,
            )

            if response.choices:
                result = response.choices[0].message.content.strip()
                try:
                    rule_data = json.loads(result, strict=False)
                    rule_type = rule_data.get('type', '').lower()
                    rule_expression = rule_data.get('rule', '')

                    if rule_type == 'buy':
                        return rule_expression, no_update
                    elif rule_type == 'sell':
                        return no_update, rule_expression
                    else:
                        return no_update, no_update
                except json.JSONDecodeError:
                    return no_update, no_update
            else:
                return no_update, no_update

        except Exception as e:
            # Handle exceptions raised by the OpenAI API call
            print(f"An error occurred: {e}")
            return no_update, no_update
        
    # Define a callback to update the cached API key
    @app.callback(
        Output("input-openai-api-key", "value"),
        [Input("input-openai-api-key", "value")]
    )
    def update_cached_api_key(new_api_key):
        update_or_verify_api_key(new_api_key, cache_file)
        return new_api_key