import dash_bootstrap_components as dbc
from dash import dcc, no_update, html, ctx
from dash.dependencies import Input, Output, State, MATCH, ALL

from dash.exceptions import PreventUpdate
from openai import OpenAI
import json
import os
import pandas as pd

from conf import PREPROC_FILENAME

available_columns = pd.read_csv(PREPROC_FILENAME).columns.tolist()
available_columns_list = "', '".join(available_columns)

context_description = f"""
The context includes the following functions:

- historic(col): Retrieves the entire vector of values for the specified column. The available columns are same as below.
- n_days_ago(col, n): Retrieves the value of the specified column n days ago. The available columns are same as below.
- current(col): Retrieves the current value of the specified column. The available columns/indicators are '{available_columns_list}'

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
        "Add Rule",
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
                placeholder="Enter GPT Prompt"
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
        Output("rule-generation-modal", "is_open", allow_duplicate=True),
        [Input({'type': 'generate-rule-button', 'index': ALL}, 'n_clicks'),
        Input("close-modal-button", "n_clicks"),
        Input("apply-modal-button", "n_clicks")],
        [State("rule-generation-modal", "is_open")],
        prevent_initial_call=True
    )
    def toggle_modal(*args):
        button_clicks, _, _, is_modal_open = args
        
        # Check if any button was clicked. Assumes button_clicks is a list of click counts.
        if any(click > 0 for click in button_clicks):
            return not is_modal_open
        
        # If no buttons were clicked, return the current state of the modal.
        return is_modal_open

def generate_rule(rule_instruction, openai_api_key):
    if not rule_instruction:
        print("Invalid prompt entered.")
        return None, False
    elif rule_instruction == "sell":
        return '', 'sell'
    elif rule_instruction == "buy":
        return '', 'buy'
    
    if not openai_api_key:
        print("OpenAI Key is missing.")
        return None, False

    messages = [
        {"role": "system", "content": f"Here is the eval context that you can use: {context_description}"},
        {"role": "user", "content": f"Natural language instruction: {rule_instruction}\n\nGenerate a Python expression for the trading rule and specify whether it is a buying or selling rule. Return your response in a JSON format. Use double quotes for strings. The JSON format should be exactly as follows: {{\"rule\": \"python_expression\", \"type\": \"buy\" or \"sell\"}}. Ensure proper JSON formatting to avoid parsing errors. \nMax date is 2024-03-04. \nIf you aggregate data, make sure to call functions like .all() and .min() on the Series or array of values within the DataFrame, for example historic('price').min(). Avoid syntax like min(historic('price')) since this causes errors. You can use numpy as np, and pandas as pd."}
    ]

    try:
        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=messages,
            max_tokens=200,
            n=1,
            stop=None,
            temperature=0.7,
        )

        if response.choices:
            result = response.choices[0].message.content.strip()
            try:
                cleaned_result = result.strip('```json').strip('```').strip()
                rule_data = json.loads(cleaned_result, strict=False)
                rule_type = rule_data.get('type', '').lower()
                rule_expression = rule_data.get('rule', '')
                return rule_expression, rule_type
            except Exception as e:
                print("Error parsing rule data")
                return e, "Rule Error"
    
    except Exception as e:
        print(f"Error: {e}")
        return e, "GPT Error"
