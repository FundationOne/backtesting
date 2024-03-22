import dash_bootstrap_components as dbc

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