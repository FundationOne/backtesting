import dash_bootstrap_components as dbc
from dash import dcc, no_update, html, ctx
from dash.dependencies import Input, Output, State, MATCH, ALL

from dash.exceptions import PreventUpdate
from openai import OpenAI
import json
import os

context_description = """
The context includes the following functions:

- last_highest(col): Returns the highest value of the specified column since the start of the data.
- last_lowest(col): Returns the lowest value of the specified column since the start of the data.
- moving_average(col, window=3): Calculates the simple moving average of the specified column over the given window size.
- current(col): Retrieves the current value of the specified column. Columns include Price, High, Low, Vol., and Change %, and are case-sensitive.
- rsi(window=14): Computes the Relative Strength Index (RSI) for the specified window size.
- macd(fast=12, slow=26, signal=9): Calculates the Moving Average Convergence Divergence (MACD) value and its signal line with the given parameters.
- bollinger_bands(window=20, num_std=2): Determines the upper and lower Bollinger Bands for the specified window size and standard deviation count.
- ema(window=20): Calculates the Exponential Moving Average (EMA) for the specified window size.
- stochastic_oscillator(k_window=14, d_window=3): Computes the Stochastic Oscillator values (%K and %D) using the given window sizes.
- average_true_range(window=14): Calculates the Average True Range (ATR) over the specified window size.
- on_balance_volume(): Calculates the On-Balance Volume (OBV).
- momentum(window=14): Computes the Momentum indicator for the specified window size.
- roi(entry_price, exit_price): Calculates the Return on Investment (ROI) between the entry and exit prices.
- stop_loss(entry_price, percentage=10): Determines the stop-loss price given an entry price and a percentage.
- take_profit(entry_price, percentage=20): Determines the take-profit price given an entry price and a percentage.
- percent_change(periods=1): Calculates the percentage change in price over the specified number of periods.
- volatility(window=20): Calculates the volatility of the price data over the specified window size.
- atr_percent(window=14): Calculates the Average True Range Percent (ATR%) over the given window size.
- ichimoku_cloud(conversion_window=9, base_window=26, lagging_window=52): Computes the Ichimoku Cloud indicator with the given parameters.
- parabolic_sar(af=0.02, max_af=0.2): Calculates the Parabolic SAR (Stop and Reverse) for the given acceleration factor and maximum AF.
- find_support_resistance(data, window=20): Identifies potential support and resistance levels using price peaks and troughs.
- volume_spike_detection(volume_data, window=20, threshold=2): Detects significant volume spikes based on the given window size and threshold.
- find_head_and_shoulders(data, window=20): Identifies Head and Shoulders patterns within the given window size.
- find_inverse_head_and_shoulders(data, window=20): Identifies Inverse Head and Shoulders patterns within the given window size.
- find_triple_top(data, window=20, tolerance=0.05): Detects Triple Top reversal patterns based on the given tolerance.
- find_triple_bottom(data, window=20, tolerance=0.05): Detects Triple Bottom reversal patterns based on the given tolerance.
- find_double_top(data, window=20, tolerance=0.05): Identifies Double Top patterns within the specified tolerance.
- fibonacci_retracement(start, end): Calculates Fibonacci retracement levels between specified start and end points.
- days_since_last_halving(): Returns the number of days since the last Bitcoin halving event.
- power_law(start_date, end_date): Returns the power law exponent for the given date range.
- price_power_law_relation(start_date, end_date): Returns the ratio of the actual prices to the power law prices for the given date range.

Other variables:
- available_cash: The amount of cash available for buying Bitcoin.
- btc_owned: The amount of Bitcoin currently owned.
- price: The current price of Bitcoin.
"""
# Natural language input for rule generation
def create_rule_generation_button(index):
    return dbc.Button(
        "Generate Rule",
        id={
            'type': 'generate-rule-button',  # Constant type for all buttons of this kind
            'index': index  # Unique index for each button
        },
        n_clicks=0,
        style={"padding": "10px 5px"}
    )

# The modal which will be reused for both buy and sell rule inputs
rule_generation_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle("Generate Rule")),
        dbc.ModalBody(
            dcc.Input(
                id="input-generate-rule",
                type="text",
                placeholder="Enter natural language instruction"
            )
        ),
        dbc.ModalFooter([
            dbc.Button("Generate Rule", id="apply-modal-button", className="ml-auto"),
            dbc.Button("Close", id="close-modal-button", className="ml-auto")]
        ),
    ],
    id="rule-generation-modal",
    is_open=False,
)


def register_callbacks(app):
    # Callbacks to open and close the modal
    @app.callback(
        Output("rule-generation-modal", "is_open"),
        [Input({'type': 'generate-rule-button', 'index': ALL}, 'n_clicks'),
        Input("close-modal-button", "n_clicks"),
        Input("apply-modal-button", "n_clicks")],
        [State("rule-generation-modal", "is_open")]
    )
    def toggle_modal(*args):
        button_clicks, _, _, is_modal_open = args
        
        # Check if any button was clicked. Assumes button_clicks is a list of click counts.
        if any(click > 0 for click in button_clicks):
            return not is_modal_open
        
        # If no buttons were clicked, return the current state of the modal.
        return is_modal_open

    @app.callback(
        [Output('input-buying-rule', 'value'),
        Output('input-selling-rule', 'value')],
        Input('apply-modal-button', 'n_clicks'),
        [State('input-generate-rule', 'value'),
        State('input-openai-api-key', 'value')]
    )
    def generate_rules(apply_rule_trigger, rule_instruction, openai_api_key):
        if not rule_instruction:
            print("Invalid prompt entered.")
            raise PreventUpdate
            
        if not openai_api_key:
            print("OpenAI Key is missing.")
            raise PreventUpdate

        messages = [
            {"role": "system", "content": f"Here is the eval context that you can use: {context_description}"},
            {"role": "user", "content": f"Natural language instruction: {rule_instruction}\n\nGenerate a Python expression for the trading rule and specify whether it is a buying or selling rule. Return your response in a JSON format. Use double quotes for strings. The JSON format should be exactly as follows: {{\"rule\": \"python_expression\", \"type\": \"buy\" or \"sell\"}}. Ensure proper JSON formatting to avoid parsing errors."}
        ]

        try:
            client = OpenAI(api_key=openai_api_key)
            response = client.chat.completions.create(
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