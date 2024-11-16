import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table, Input, Output, State
import pandas as pd
import numpy as np
import plotly.graph_objs as go
from matplotlib.colors import Normalize
from matplotlib import cm

# Functions to generate scenarios and calculate values
def generate_risk_band_scenarios(band_indices, max_length=7, total_combinations=100):
    scenarios = []
    queue = [[band_indices[0]]]  # Start from the first band index

    while queue and len(scenarios) < total_combinations:
        path = queue.pop(0)
        scenarios.append(path)
        if len(path) < max_length:
            current = path[-1]
            for next_band in [current + 1, current -1]:
                if 0 <= next_band < len(band_indices):
                    new_path = path + [next_band]
                    queue.append(new_path)

    return scenarios[:total_combinations]

def calculate_scenario_value(scenario, stop_loss_prices, trigger_prices, percentage_pushed):
    total_btc = 1  # Start with 1 BTC
    capital = 0   # Start with $0

    percentage_pushed = percentage_pushed / 100.0  # Convert percentage to fraction

    for i in range(1, len(scenario)):
        current_band_index = scenario[i - 1]
        next_band_index = scenario[i]

        # Use Trigger Price when moving up, Stop Loss Price when moving down
        if next_band_index > current_band_index:
            price = trigger_prices[current_band_index]
        else:
            price = stop_loss_prices[current_band_index]

        # Sell percentage_pushed of BTC at the price
        btc_to_sell = percentage_pushed * total_btc
        sale_value = btc_to_sell * price
        capital += sale_value
        total_btc -= btc_to_sell

    # Add final BTC value at the last band's Stop Loss Price
    final_band_index = scenario[-1]
    final_price = stop_loss_prices[final_band_index]
    capital += total_btc * final_price

    return capital

# Corrected default values (from low band to high band)
default_stop_loss_prices = [79000, 87600, 110800, 137200, 166900]
default_trigger_prices = [90850, 100740, 127420, 157780, 191935]
default_percentage_pushed = 20  # Default percentage pushed to next level

# Define the number of risk bands
num_bands = len(default_stop_loss_prices)

# Create initial DataFrame
stop_loss_prices_list = default_stop_loss_prices
trigger_prices_list = default_trigger_prices
band_indices = list(range(len(stop_loss_prices_list)))

scenarios = generate_risk_band_scenarios(band_indices)
scenario_values = []
for idx, scenario in enumerate(scenarios):
    total_value = calculate_scenario_value(scenario, stop_loss_prices_list, trigger_prices_list, default_percentage_pushed)
    scenario_str = ' -> '.join([f"Band {band_index + 1}" for band_index in scenario])
    scenario_values.append({'Scenario': scenario_str, 'Total Value': total_value})

df_dash = pd.DataFrame(scenario_values)
df_dash = df_dash.sort_values(by='Total Value', ascending=False)
df_dash['Total Value'] = df_dash['Total Value'].apply(lambda x: f"${x:,.2f}")

# Create input fields for each risk band
risk_band_inputs = []
for i in range(num_bands):
    risk_band_inputs.append(
        dbc.Row([
            dbc.Col(html.Label(f"Risk Band {i+1}"), width=4),
            dbc.Col(
                dbc.Input(
                    id=f"stop-loss-price-{i+1}",
                    type="number",
                    placeholder="Stop Loss Price",
                    value=stop_loss_prices_list[i],
                    style={"width": "100%"}
                ), width=4
            ),
            dbc.Col(
                dbc.Input(
                    id=f"trigger-price-{i+1}",
                    type="number",
                    placeholder="Trigger Price",
                    value=trigger_prices_list[i],
                    style={"width": "100%"}
                ), width=4
            ),
        ], style={"marginBottom": "10px"})
    )

# Define the layout for the riskbands page
layout = dbc.Container(
    [
        dbc.Row([
            # Input fields on the left
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H5("Risk Band Stop Loss Prices and Triggers"),
                        html.Hr(),
                        *risk_band_inputs,
                        # Input for percentage pushed to next level
                        dbc.Row([
                            dbc.Label("Percentage Pushed to Next Level (%)", html_for="input-percentage", width=12),
                            dbc.Col([
                                dbc.Input(
                                    id="input-percentage",
                                    type="number",
                                    value=default_percentage_pushed,
                                    min=0,
                                    max=100,
                                    step=0.1,
                                    style={"width": "100%"}
                                )
                            ], width=12)
                        ])
                    ])
                ], style={"border": "unset"})
            ], sm=12, md=4, style={"padding": "0px"}),
            # Chart and table on the right
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dcc.Graph(id='scenario-graph'),
                        dash_table.DataTable(
                            id='scenario-table',
                            columns=[
                                {'name': 'Scenario', 'id': 'Scenario'},
                                {'name': 'Total Value', 'id': 'Total Value'}
                            ],
                            data=df_dash.to_dict('records'),
                            style_table={'height': '600px', 'overflowY': 'auto'},
                            style_cell={'textAlign': 'left', 'padding': '5px'},
                            style_header={
                                'backgroundColor': 'rgb(230, 230, 230)',
                                'fontWeight': 'bold'
                            },
                            page_size=20
                        )
                    ])
                ])
            ], sm=12, md=8, style={"padding": "0px"})
        ], style={"marginTop": "20px"})
    ],
    className="container"
)

# Register the callbacks for the riskbands page
def register_callbacks(app):
    @app.callback(
        [Output('scenario-graph', 'figure'),
         Output('scenario-table', 'data')],
        [Input(f'stop-loss-price-{i+1}', 'value') for i in range(num_bands)] +
        [Input(f'trigger-price-{i+1}', 'value') for i in range(num_bands)] +
        [Input('input-percentage', 'value')]
    )
    def update_scenarios(*args):
        percentage_pushed = args[-1]
        stop_loss_prices = args[:num_bands]
        trigger_prices = args[num_bands:-1]

        # Validate inputs
        if None in stop_loss_prices or None in trigger_prices or percentage_pushed is None:
            return go.Figure(), []

        band_indices = list(range(len(stop_loss_prices)))

        # Generate scenarios
        scenarios = generate_risk_band_scenarios(band_indices)
        scenario_values = []
        lines = []

        for idx, scenario in enumerate(scenarios):
            total_value = calculate_scenario_value(scenario, stop_loss_prices, trigger_prices, percentage_pushed)
            scenario_str = ' -> '.join([f"Band {band_index + 1}" for band_index in scenario])
            scenario_values.append({'Scenario': scenario_str, 'Total Value': total_value})
            steps = np.array(range(len(scenario)), dtype=float)
            bands = [stop_loss_prices[band_index] for band_index in scenario]

            # Add a small offset to the x-values based on scenario index
            x_offset = idx * 0.1  # Adjust this value to control spacing
            steps = steps + x_offset

            # Append line data and total value
            lines.append((go.Scatter(), total_value, steps, bands, scenario))

        # Normalize colors based on total values
        total_values = [total_value for _, total_value, _, _, _ in lines]
        min_total_value = min(total_values)
        max_total_value = max(total_values)
        norm = Normalize(vmin=min_total_value, vmax=max_total_value)
        cmap = cm.get_cmap('RdYlGn')

        # Create the figure
        fig = go.Figure()

        # Plot each line with appropriate color
        for line_data, total_value, steps, bands, scenario in lines:
            rgba_color = cmap(norm(total_value))
            line_color = 'rgba({},{},{},{})'.format(
                int(rgba_color[0]*255),
                int(rgba_color[1]*255),
                int(rgba_color[2]*255),
                0.5  # Adjust transparency as needed
            )
            line_data = go.Scatter(
                x=steps,
                y=bands,
                mode='lines',
                line=dict(
                    color=line_color,
                    width=2  # Adjust line width as desired
                ),
                hoverinfo='text',
                text=[f"Step: {i:.2f}<br>Band: {band_index + 1}<br>Stop Loss: ${stop_loss_prices[band_index]:,.2f}<br>Trigger: ${trigger_prices[band_index]:,.2f}" for i, band_index in zip(steps, scenario)],
                showlegend=False
            )
            fig.add_trace(line_data)

        # Create a dummy scatter trace for the colorbar
        colorbar_trace = go.Scatter(
            x=[None],
            y=[None],
            mode='markers',
            marker=dict(
                colorscale='RdYlGn',
                showscale=True,
                cmin=min_total_value,
                cmax=max_total_value,
                colorbar=dict(
                    title='Total Value',
                    titleside='right'
                ),
                color=[min_total_value]  # Dummy value
            ),
            hoverinfo='none',
            showlegend=False
        )
        fig.add_trace(colorbar_trace)

        # Update figure layout
        fig.update_layout(
            title='Risk Band Scenarios: Value at Each Step',
            xaxis_title='Step Number (with Offset)',
            yaxis_title='Stop Loss Price (USD)',
            yaxis=dict(
                tickmode='array',
                tickvals=stop_loss_prices,
                ticktext=[f"${level:,.2f}" for level in stop_loss_prices]
            ),
            showlegend=False,
            height=600
        )

        # Create a DataFrame for the table
        df_scenarios = pd.DataFrame(scenario_values)
        df_scenarios = df_scenarios.sort_values(by='Total Value', ascending=False)
        df_scenarios['Total Value'] = df_scenarios['Total Value'].apply(lambda x: f"${x:,.2f}")

        # Return the figure and table data
        return fig, df_scenarios.to_dict('records')
