import dash_bootstrap_components as dbc
from dash import dcc, html, ctx, no_update
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate
import json

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
        # style={"padding": "10px 5px"}
    )


def create_rule_input(rule_type, rule_index, rule_expression):
    type_label = html.Div(rule_type.capitalize(), style={
        "writingMode": "vertical-lr",
        "margin": "0px 7px",
        "width": "20px",
        "color": "#555"
    })

    input_field = dcc.Textarea(
        id={"type": f"{rule_type}-rule", "index": rule_index},
        value=rule_expression,
        rows=2
    )

    remove_button = dbc.Button(
        children="➖",
        id={"type": f"remove-rule", "index": rule_index},
        n_clicks=0,
        style={"padding": "0.25rem 0.5rem", "border": "none", "backgroundColor": "transparent"},
    )
    return dbc.ListGroupItem(
        [type_label, input_field, remove_button],
        style={"display": "flex", "alignItems": "center", "left":"8px", "maxWidth":"94%", "width":"94%"}
    )

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
                dcc.Dropdown(id="load-rules-dropdown")
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="cancel-load-rules-modal", className="ml-auto"),
                dbc.Button("Delete Rules", id="delete-rule-set-button", className="ml-auto", n_clicks=0),
                dbc.Button("Load Rules", id="confirm-load-rules-modal", className="ml-auto"),
            ])
        ], id="load-rules-modal")
    ])

def prepare_rules_to_store(rule_name, children):
    rules = {
        "buying_rule": [],
        "selling_rule": []
    }

    for child in children:
        textarea = child['props']['children'][1]
        textarea_props = textarea['props']
        rule_type = textarea_props['id']['type']
        rule_value = textarea_props['value'].strip()

        if rule_type == "buy-rule" and rule_value:
            rules["buying_rule"].append(rule_value)
        elif rule_type == "sell-rule" and rule_value:
            rules["selling_rule"].append(rule_value)

    return rule_name, rules

def get_saved_rules_names(store_data):
    if store_data is not None:
        return list(store_data.keys())
    else:
        return []

def load_rules_from_store(rule_name, store_data):
    if rule_name == "default_ruleset":
        buying_rules = store_data.get("default_ruleset", {}).get("buying_rule", [])
        selling_rules = store_data.get("default_ruleset", {}).get("selling_rule", [])
    else:
        rules = store_data.get(rule_name, {"buying_rule": [], "selling_rule": []})
        buying_rules = rules.get("buying_rule", [])
        selling_rules = rules.get("selling_rule", [])

    children = []
    for i, rule in enumerate(buying_rules):
        children.append(create_rule_input("buy", i, rule))

    for i, rule in enumerate(selling_rules):
        children.append(create_rule_input("sell", i + len(buying_rules), rule))

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
    # @app.callback(
    #     Output("rule-generation-modal", "is_open", allow_duplicate=True),
    #     [Input({'type': 'generate-rule-button', 'index': ALL}, 'n_clicks'),
    #     Input("close-modal-button", "n_clicks"),
    #     Input("apply-modal-button", "n_clicks"),
    #     Input("apply-modal-button-sell", "n_clicks"),
    #     Input("apply-modal-button-buy", "n_clicks")],
    #     [State("rule-generation-modal", "is_open")],
    #     prevent_initial_call=True
    # )
    # def toggle_modal(*args):
    #     button_clicks, _, _, _, _, is_modal_open = args
        
    #     # Check if any button was clicked. Assumes button_clicks is a list of click counts.
    #     if any(click > 0 for click in button_clicks):
    #         return not is_modal_open
        
    #     # If no buttons were clicked, return the current state of the modal.
    #     return is_modal_open
    
    
    @app.callback(
        [Output("trading-rules-container", "children"),
        Output("rule-generation-modal", "is_open")],
        [Input({'type': 'generate-rule-button', 'index': ALL}, 'n_clicks'),
        Input("apply-modal-button", "n_clicks"),
        Input("apply-modal-button-buy", "n_clicks"),
        Input("apply-modal-button-sell", "n_clicks"),
        Input("close-modal-button", "n_clicks")],
        [State("trading-rules-container", "children"),
        State("input-generate-rule", "value"),
        State("input-openai-api-key", "value"),
        State("rule-generation-modal", "is_open"),
        State("saved-rules-store", "data")],
        prevent_initial_call=True
    )
    def toggle_generate_rules_modal(generate_rule_clicks, apply_modal_click, apply_modal_buy_click, apply_modal_sell_click, close_modal_click, children, rule_instruction, openai_api_key, is_modal_open, store_data):
        trigger_id = ctx.triggered[0]["prop_id"] if ctx.triggered else None
        try:
            button_clicked = json.loads(trigger_id.split(".")[0]) if trigger_id else None
        except Exception as e:
            button_clicked = None

        if button_clicked and button_clicked.get("type") == "generate-rule-button":
            return children, True  # Open the modal

        elif trigger_id == "apply-modal-button-buy.n_clicks":
            children.append(create_rule_input("buy", len(children), ""))
            return children, False  # Close the modal after adding the new rule
        
        elif trigger_id == "apply-modal-button-sell.n_clicks":
            children.append(create_rule_input("sell", len(children), ""))
            return children, False  # Close the modal after adding the new rule
        
        elif trigger_id == "apply-modal-button.n_clicks":
            if not rule_instruction:
                return children, is_modal_open
            
            rule_expression, rule_type = generate_rule(rule_instruction, openai_api_key)
            children.append(create_rule_input(rule_type, len(children), rule_expression))

            return children, False  # Close the modal after adding the new rule

        elif trigger_id == "close-modal-button.n_clicks":
            return children, False  # Close the modal

        return children, is_modal_open

    @app.callback(
        Output("trading-rules-container", "children", allow_duplicate=True),
        [Input({"type": "remove-rule", "index": ALL}, "n_clicks")],
        [State("trading-rules-container", "children")],
        prevent_initial_call=True
    )
    def remove_rule(remove_clicks, children):
        if not ctx.triggered or all(click == 0 for click in remove_clicks):
            raise PreventUpdate

        # Determine which button was clicked
        button_id = ctx.triggered[0]['prop_id']
        index_to_remove = json.loads(button_id.split('.')[0])['index']

        # Remove the corresponding child based on the index
        new_children = [child for i, child in enumerate(children) if i != index_to_remove]
        
        return new_children 
    
    @app.callback(
        Output("trading-rules-container", "children", allow_duplicate=True),
        [Input("confirm-load-rules-modal", "n_clicks"), 
         Input("saved-rules-store", "data")],
        [State("load-rules-dropdown", "value")],
        prevent_initial_call=True
    )
    def update_trading_rules_container(submit_n_clicks, store_data, selected_rule):
        trigger_id = ctx.triggered_id if ctx.triggered_id else None
        if trigger_id == 'saved-rules-store':
            if not selected_rule:
                children = load_rules_from_store("default_ruleset", store_data)
                return children
            return no_update
        
        elif submit_n_clicks and selected_rule:
            children = load_rules_from_store(selected_rule, store_data)
            return children

        raise PreventUpdate

    @app.callback(
        [Output("save-rules-modal", "is_open"),
        Output("saved-rules-store", "data", allow_duplicate=True)],
        [Input("open-save-rules-modal", "n_clicks"), 
         Input("confirm-save-rules-modal", "n_clicks"), 
         Input("cancel-save-rules-modal", "n_clicks")],
        [State("save-rules-modal", "is_open"), 
         State("save-rules-input", "value"), 
         State("trading-rules-container", "children"), 
         State("saved-rules-store", "data")],
        prevent_initial_call=True
    )
    def toggle_save_rules_modal(open_n_clicks, submit_n_clicks, cancel_n_clicks, is_open, rule_name, children, store_data):
        trigger_id = ctx.triggered_id if ctx.triggered_id else None

        if trigger_id == "open-save-rules-modal":
            return True, no_update
        
        elif trigger_id == "cancel-save-rules-modal":
            return False, no_update
        
        elif trigger_id == "confirm-save-rules-modal" and rule_name:
            _, rules = prepare_rules_to_store(rule_name, children)

            updated_store_data = store_data if store_data else {}
            updated_store_data[rule_name] = rules

            return False, updated_store_data

        return is_open, no_update

    @app.callback(
        [Output("load-rules-modal", "is_open"), 
         Output("load-rules-dropdown", "options", allow_duplicate=True)],
        [
            Input("open-load-rules-modal", "n_clicks"),
            Input("confirm-load-rules-modal", "n_clicks"),
            Input("cancel-load-rules-modal", "n_clicks"),
            Input("saved-rules-store", "data"),
        ],
        [State("load-rules-modal", "is_open"), 
         State("load-rules-dropdown", "value")],
         prevent_initial_call=True
    )
    def toggle_load_rules_modal(open_n_clicks, submit_n_clicks, cancel_n_clicks, store_data, is_open, selected_rule):
        trigger_id = ctx.triggered_id if ctx.triggered_id else None

        if trigger_id == "open-load-rules-modal":
            options = [{"label": name, "value": name} for name in get_saved_rules_names(store_data)]
            return True, options
        
        elif trigger_id == "confirm-load-rules-modal" and selected_rule:
            return False, []
        
        elif trigger_id == "cancel-load-rules-modal":
            return False, []
        
        options = [{"label": name, "value": name} for name in get_saved_rules_names(store_data)]
        return is_open, options

    @app.callback(
        [Output("load-rules-dropdown", "options", allow_duplicate=True),
        Output("saved-rules-store", "data", allow_duplicate=True)],
        [Input("delete-rule-set-button", "n_clicks")],
        [State("load-rules-dropdown", "value"),
        State("saved-rules-store", "data")],
        prevent_initial_call=True
    )
    def delete_rule_set(delete_n_clicks, selected_rule, store_data):
        if delete_n_clicks > 0 and selected_rule and store_data:
            if selected_rule in store_data:
                del store_data[selected_rule]
                options = [{"label": name, "value": name} for name in store_data.keys()]
                return options, store_data
        raise PreventUpdate

    @app.callback(
        Output("saved-rules-store", "data"),
        Input("saved-rules-store", "data")
    )
    def initialize_rule_store(data):
        if data is None:  # Checks if the store is uninitialized
            default_rule = "current('price') < current('power_law_price_4y_window')"
            saved_rules = {
                "default_ruleset": {
                    "buying_rule": [default_rule],
                    "selling_rule": []
                }
            }
            return saved_rules  # Initializes the store with default data
        return data  # Returns the existing data if already initialized