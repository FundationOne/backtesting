import dash_bootstrap_components as dbc
from dash import dcc, no_update, html, ctx
from dash.dependencies import Input, Output, State, MATCH, ALL

from dash.exceptions import PreventUpdate
from openai import OpenAI
import json
import os

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