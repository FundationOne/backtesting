import dash_bootstrap_components as dbc
from dash import dcc, html, ctx
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate
import json
from utils import *

from dash.exceptions import PreventUpdate
from conf import *

from gpt_functionality import generate_rule

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


def create_rule_input(rule_type, rule_values, rule_expression):
    type_label = html.Div(rule_type.capitalize(), style={
        "writingMode": "vertical-lr",
        "margin": "0px 7px",
        "width": "20px",
        "color": "#555"
    })

    input_field = dcc.Textarea(
        id={"type": f"{rule_type}-rule", "index": len(rule_values)},
        value=rule_expression,
        rows=2
    )

    remove_button = dbc.Button(
        children="➖",
        id={"type": f"remove-rule", "index": len(rule_values)},
        n_clicks=0,
        style={"padding": "0.25rem 0.5rem", "border": "none", "backgroundColor": "transparent"},
    )
    return dbc.ListGroupItem(
        [type_label, input_field, remove_button],
        style={"display": "flex", "alignItems": "center", "left":"7px", "maxWidth":"100%", "width":"100%"}
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



def save_rules_modal():
    return html.Div([
        dbc.Modal([
            dbc.ModalHeader("Save Rules"),
            dbc.ModalBody([
                dcc.Input(id="save-rules-input", type="text", placeholder="Name to save rules as"),
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="cancel-save-rules-modal", className="ml-auto"),
                dbc.Button("Save Rules", id="confirm-save-rules-modal", className="ml-auto"),
            ])
        ], id="save-rules-modal")
    ])

def load_rules_modal():
    return html.Div([
        dbc.Modal([
            dbc.ModalHeader("Load Rules"),
            dbc.ModalBody([
                dcc.Dropdown(id="load-rules-dropdown"),  # Options will be populated dynamically
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="cancel-load-rules-modal", className="ml-auto"),
                dbc.Button("Load Rules", id="confirm-load-rules-modal", className="ml-auto"),
            ])
        ], id="load-rules-modal")
    ])


def save_rules_to_store(rule_name, children, store):
    buying_rule, selling_rule = get_rules_from_input(children)
    rules = {"buying_rule": buying_rule, "selling_rule": selling_rule}
    saved_rules = json.loads(store.get("saved_rules") or "{}")
    saved_rules[rule_name] = rules
    store.set("saved_rules", json.dumps(saved_rules))

def get_saved_rules_names(store):
    if store is not None:
        saved_rules = json.loads(store.get("saved_rules") or "{}")
        return list(saved_rules.keys())
    else:
        return {}

def load_rules_from_store(rule_name, store_data):
    saved_rules = json.loads(store_data.get("saved_rules") or "{}")
    rules = saved_rules.get(rule_name, {})
    buying_rule = rules.get("buying_rule", "")
    selling_rule = rules.get("selling_rule", "")

    children = [
        create_rule_input("buy", range(1), buying_rule),
        create_rule_input("sell", range(1), selling_rule),
    ]
    return children


# The modal which will be reused for both buy and sell rule inputs
rule_generation_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle("Add New Rule")),
        dbc.ModalBody(
            dcc.Input(
                id="input-generate-rule",
                type="text",
                placeholder="Enter GPT Prompt"
            )
        ),
        dbc.ModalFooter([
            dbc.Button("Add Empty Sell", id="apply-modal-button-sell", className="ml-auto", 
                       style={"backgroundColor": "#d6d6d6", "color": "black", "fontSize": "0.7rem", "padding": "10px"}),
            dbc.Button("Add Empty Buy", id="apply-modal-button-buy", className="ml-auto", 
                       style={"backgroundColor": "#d6d6d6", "color": "black", "fontSize": "0.7rem", "padding": "10px"}),
            dbc.Button("Generate Rule", id="apply-modal-button", className="ml-auto"),
            dbc.Button("Close", id="close-modal-button", className="ml-auto", style={"display":"none"})
            ]
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
        Input("apply-modal-button", "n_clicks"),
        Input("apply-modal-button-sell", "n_clicks"),
        Input("apply-modal-button-buy", "n_clicks")],
        [State("rule-generation-modal", "is_open")],
        prevent_initial_call=True
    )
    def toggle_modal(*args):
        button_clicks, _, _, _, _, is_modal_open = args
        
        # Check if any button was clicked. Assumes button_clicks is a list of click counts.
        if any(click > 0 for click in button_clicks):
            return not is_modal_open
        
        # If no buttons were clicked, return the current state of the modal.
        return is_modal_open
    
    @app.callback(
        [Output("load-rules-modal", "is_open"), Output("load-rules-modal", "input_options")],
        [
            Input("open-load-rules-modal", "n_clicks"),
            Input("load-rules-modal", "submit_n_clicks"),
            Input("load-rules-modal", "cancel_n_clicks"),
            Input("saved-rules-store", "data"),
        ],
        [State("load-rules-modal", "is_open"), State("load-rules-modal", "input_value")],
    )
    def toggle_load_rules_modal(
        open_n_clicks, submit_n_clicks, cancel_n_clicks, store_data, is_open, selected_rule
    ):
        trigger_id = ctx.triggered_id if ctx.triggered_id else None

        if trigger_id == "open-load-rules-modal":
            options = [{"label": name, "value": name} for name in get_saved_rules_names(store_data)]
            return True, options
        elif trigger_id == "load-rules-modal.submit_n_clicks" and selected_rule:
            load_rules_from_store(selected_rule)
            return False, []
        elif trigger_id == "load-rules-modal.cancel_n_clicks":
            return False, []
        return is_open, []

    
    @app.callback(
        [Output("trading-rules-container", "children"),
        Output("rule-generation-modal", "is_open")],
        [Input({'type': 'generate-rule-button', 'index': ALL}, 'n_clicks'),
        Input({"type": "remove-rule", "index": ALL}, "n_clicks"),
        Input("apply-modal-button", "n_clicks"),
        Input("apply-modal-button-buy", "n_clicks"),
        Input("apply-modal-button-sell", "n_clicks"),
        Input("close-modal-button", "n_clicks")],
        [State("trading-rules-container", "children"),
        State({"type": "buying-rule", "index": ALL}, "value"),
        State("input-generate-rule", "value"),
        State("input-openai-api-key", "value"),
        State("rule-generation-modal", "is_open")],
        prevent_initial_call=True
    )
    def generate_rules(generate_rule_clicks, remove_clicks, apply_modal_click, apply_modal_buy_click, apply_modal_sell_click, close_modal_click, children, rule_values, rule_instruction, openai_api_key, is_modal_open):
        trigger_id = ctx.triggered[0]["prop_id"] if ctx.triggered else None
        try:
            button_clicked = json.loads(trigger_id.split(".")[0]) if trigger_id else None
        except Exception as e:
            button_clicked = None

        if button_clicked and button_clicked.get("type") == "generate-rule-button":
            return children, True  # Open the modal

        elif trigger_id == "apply-modal-button-buy.n_clicks":
            children.append(create_rule_input("buy", rule_values, ""))
            return children, False  # Close the modal after adding the new rule
        elif trigger_id == "apply-modal-button-sell.n_clicks":
            children.append(create_rule_input("sell", rule_values, ""))
            return children, False  # Close the modal after adding the new rule
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
        
    @app.callback(
        Output("trading-rules-container", "children", allow_duplicate=True),
        [Input("load-rules-modal", "submit_n_clicks"), 
         Input("saved-rules-store", "data")],
        [State("load-rules-modal", "input_value")],
        prevent_initial_call=True
    )
    def update_trading_rules_container(submit_n_clicks, store_data, selected_rule):
        if submit_n_clicks and selected_rule:
            # Assuming load_rules_from_store now correctly handles store_data and returns UI components
            children = load_rules_from_store(selected_rule, store_data)
            return children
        raise PreventUpdate

    @app.callback(
        Output("save-rules-modal", "is_open"),
        [Input("open-save-rules-modal", "n_clicks"), Input("save-rules-modal", "submit_n_clicks"), Input("save-rules-modal", "cancel_n_clicks")],
        [State("save-rules-modal", "is_open"), State("save-rules-modal", "input_value"), State("trading-rules-container", "children")],
        prevent_initial_call=True
    )
    def toggle_save_rules_modal(open_n_clicks, submit_n_clicks, cancel_n_clicks, is_open, rule_name, children):
        trigger_id = ctx.triggered_id if ctx.triggered_id else None

        if trigger_id == "open-save-rules-modal":
            return True
        elif trigger_id == "save-rules-modal.submit_n_clicks" and rule_name:
            save_rules_to_store(rule_name, children)
            return False
        elif trigger_id == "save-rules-modal.cancel_n_clicks":
            return False
        return is_open
