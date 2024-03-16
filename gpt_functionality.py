import dash_bootstrap_components as dbc
from dash import dcc, no_update, html, ctx
from dash.dependencies import Input, Output, State, MATCH, ALL

from dash.exceptions import PreventUpdate
from openai import OpenAI
import json
import os

context_description = """
The context includes the following functions:

- current(col): Retrieves the current value of the specified column. The available columns are 'price', 'open', 'high', 'low', 'volume', 'last_highest', 'last_lowest','sma_10','sma_20','sma_50','sma_200','sma_20_week','sma_100_week', 'rsi_14', 'macd', 'bollinger_upper', 'bollinger_lower','ema_8','ema_20','ema_50','ema_200','stochastic_oscillator', 'atr', 'on_balance_volume','momentum_14', 'percent_change', 'volatility', 'atr_percent','ichimoku_a', 'ichimoku_b', 'parabolic_sar', 'support', 'resistance','volume_spike', 'days_since_last_halving','power_law_price', 'power_law_price_1y_window','power_law_price_4y_window'
- historic(col): Retrieves the entire vector of values for the specified column. The available columns are same as above.

It also includes these variables:
- available_cash: The amount of cash available for buying Bitcoin.
- btc_owned: The amount of Bitcoin currently owned.
- current_portfolio_value: How much is the current portfolio worth.
- portfolio_value_over_time: A vector of the portfolio value up to today
- current_date: the current date as 'YYYY-MM-DD'
- current_index: the index of the current date in the historic data
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
        State('input-openai-api-key', 'value')],
        prevent_initial_call=True
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
            {"role": "user", "content": f"Natural language instruction: {rule_instruction}\n\nGenerate a Python expression for the trading rule and specify whether it is a buying or selling rule. Return your response in a JSON format. Use double quotes for strings. The JSON format should be exactly as follows: {{\"rule\": \"python_expression\", \"type\": \"buy\" or \"sell\"}}. Ensure proper JSON formatting to avoid parsing errors. Max date is 2024-03-04."}
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