import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table, ctx
from dash.dependencies import Input, Output, State, ALL

settings_scale_toggle = dbc.Row(
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
)

donate_button = dbc.Row(
    [
        dbc.Col(
            dbc.Button("Donate to Creator", id="donate-button", outline=True, color="primary"),
            width={"size": 6, "offset": 3},
        ),
    ],
    className="mb-3",
)

donate_modal = dbc.Modal(
    [
        dbc.ModalHeader("Donate to Creator"),
        dbc.ModalBody(
            [
                html.P("Thank you for considering a donation to support the development of this app."),
                html.P("You can donate using the following methods:"),
                dbc.ListGroup(
                    [
                        dbc.ListGroupItem(
                            [
                                html.Span("Dollar Donation (PayPal): "),
                                html.A("https://paypal.me/your-paypal-link", href="https://paypal.me/your-paypal-link", target="_blank"),
                            ]
                        ),
                        dbc.ListGroupItem(
                            [
                                html.Span("Bitcoin Donation: "),
                                html.Code("your-bitcoin-address"),
                            ]
                        ),
                    ]
                ),
            ]
        ),
        dbc.ModalFooter(
            dbc.Button("Close", id="close-donate-modal", className="ml-auto")
        ),
    ],
    id="donate-modal",
    is_open=False,
)

def register_callbacks(app):
    @app.callback(
        Output("donate-modal", "is_open"),
        Input("donate-button", "n_clicks"),
        [State("donate-modal", "is_open")],
    )
    def toggle_donate_modal(n_clicks, is_open):
        if n_clicks:
            return not is_open
        return is_open