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

def calculate_scenario_value(scenario, stop_loss_prices, percentage_pushed):
    total_btc = {band: 0 for band in range(len(stop_loss_prices))}  # BTC allocated to each band
    total_btc[scenario[0]] = 1  # Start with 1 BTC in the initial band
    capital = 0   # Start with $0
    btc_sold_at_each_step = []  # To record BTC sold at each step

    percentage_pushed = percentage_pushed / 100.0  # Convert percentage to fraction

    for i in range(1, len(scenario)):
        prev_band = scenario[i - 1]
        current_band = scenario[i]

        if current_band > prev_band:
            # Price moved up to a higher band
            btc_to_move = total_btc[prev_band] * percentage_pushed
            total_btc[prev_band] -= btc_to_move
            total_btc[current_band] += btc_to_move
            # No BTC is sold
            btc_sold_at_each_step.append(0)  # Append 0 as no BTC sold
        elif current_band < prev_band:
            # Price moved down to a lower band
            # Sell all BTC in the higher band at Stop Loss Price of the higher band
            btc_to_sell = total_btc[prev_band]
            sale_value = btc_to_sell * stop_loss_prices[prev_band]
            capital += sale_value
            total_btc[prev_band] = 0
            btc_sold_at_each_step.append(btc_to_sell)  # Record BTC sold
        else:
            # No movement, no action
            btc_sold_at_each_step.append(0)  # Append 0 as no BTC sold

    # After the scenario ends, calculate the value of remaining BTC holdings
    for band, btc_amount in total_btc.items():
        if btc_amount > 0:
            # Value remaining BTC at the current Stop Loss Price of the band
            capital += btc_amount * stop_loss_prices[band]

    return capital, btc_sold_at_each_step

# Corrected default values (from low band to high band)
default_stop_loss_prices = [79000, 87600, 110800, 137200, 166900]
default_probabilities = [20, 25, 30, 15, 10]  # Percentages
default_percentage_pushed = 80  # Default percentage pushed to next level

# Define the number of risk bands
num_bands = len(default_stop_loss_prices)

# Create initial DataFrame
stop_loss_prices_list = default_stop_loss_prices
probabilities_list = default_probabilities
band_indices = list(range(len(stop_loss_prices_list)))

scenarios = generate_risk_band_scenarios(band_indices)
scenario_values = []
for idx, scenario in enumerate(scenarios):
    total_value, btc_sold_at_each_step = calculate_scenario_value(scenario, stop_loss_prices_list, default_percentage_pushed)
    scenario_str = ' -> '.join([f"Band {band_index + 1}" for band_index in scenario])
    # Compute average probability for the scenario
    probabilities_of_bands_in_scenario = [probabilities_list[band_index] for band_index in scenario]
    average_probability = sum(probabilities_of_bands_in_scenario) / len(probabilities_of_bands_in_scenario)
    total_value_times_probability = total_value * (average_probability / 100.0)
    scenario_values.append({'Scenario': scenario_str, 'Total Value': total_value, 'Total Value Times Probability': total_value_times_probability})

df_dash = pd.DataFrame(scenario_values)
df_dash = df_dash.sort_values(by='Total Value', ascending=False)
df_dash['Total Value'] = df_dash['Total Value'].apply(lambda x: f"${x:,.2f}")
df_dash['Total Value Times Probability'] = df_dash['Total Value Times Probability'].apply(lambda x: f"${x:,.2f}")

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
                    id=f"probability-{i+1}",
                    type="number",
                    placeholder="Probability (%)",
                    value=probabilities_list[i],
                    style={"width": "100%"}
                ), width=4
            ),
        ], style={"marginBottom": "10px"})
    )

# Define the layout for the riskbands page
layout = html.Div(
    [
        dbc.Row([
            # Input fields on the left
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H5("Risk Band Stop Loss Prices and Probabilities"),
                        html.Hr(),
                        *risk_band_inputs,
                        # Input for percentage pushed to next level
                        dbc.Row([
                            dbc.Label("Percentage Pushed to Next Band (%)", html_for="input-percentage", width=12),
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
                        ]),
                        # Heatmap below the inputs
                        html.Div([
                            html.H5("Heatmap of Total Sums", style={"marginTop": "20px"}),
                            dcc.Graph(id='heatmap-graph')
                        ])
                    ])
                ], style={"border": "unset"})
            ], sm=12, md=4, style={"padding": "0px"}),
            # Chart and table on the right
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dcc.Graph(id='scenario-graph'),
                        # Totals Div
                        html.Div(id='totals-div', style={"marginTop": "20px"}),
                        dash_table.DataTable(
                            id='scenario-table',
                            columns=[
                                {'name': 'Scenario', 'id': 'Scenario'},
                                {'name': 'Total Value', 'id': 'Total Value'},
                                {'name': 'Total Value Times Probability', 'id': 'Total Value Times Probability'}
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
         Output('scenario-table', 'data'),
         Output('totals-div', 'children'),
         Output('heatmap-graph', 'figure')],
        [Input(f'stop-loss-price-{i+1}', 'value') for i in range(num_bands)] +
        [Input(f'probability-{i+1}', 'value') for i in range(num_bands)] +
        [Input('input-percentage', 'value')]
    )
    def update_scenarios(*args):
        percentage_pushed = args[-1]
        stop_loss_prices = args[:num_bands]
        probabilities = args[num_bands:-1]

        # Validate inputs
        if None in stop_loss_prices or None in probabilities or percentage_pushed is None:
            return go.Figure(), [], [], go.Figure()

        band_indices = list(range(len(stop_loss_prices)))

        # Generate scenarios
        scenarios = generate_risk_band_scenarios(band_indices)
        scenario_values = []
        lines = []

        for idx, scenario in enumerate(scenarios):
            total_value, btc_sold_at_each_step = calculate_scenario_value(scenario, stop_loss_prices, percentage_pushed)
            scenario_str = ' -> '.join([f"Band {band_index + 1}" for band_index in scenario])
            # Compute average probability for the scenario
            probabilities_of_bands_in_scenario = [probabilities[band_index] for band_index in scenario]
            average_probability = sum(probabilities_of_bands_in_scenario) / len(probabilities_of_bands_in_scenario)
            total_value_times_probability = total_value * (average_probability / 100.0)
            scenario_values.append({'Scenario': scenario_str, 'Total Value': total_value, 'Total Value Times Probability': total_value_times_probability})
            steps = np.array(range(len(scenario)), dtype=float)
            bands = [stop_loss_prices[band_index] for band_index in scenario]

            # Add a small offset to the x-values based on scenario index
            x_offset = idx * 0.1  # Adjust this value to control spacing
            steps = steps + x_offset

            # Prepare hover text including BTC sold at each step
            hover_text = []
            for i, band_index in enumerate(scenario):
                text = f"Step: {i}<br>Band: {band_index + 1}<br>Stop Loss: ${stop_loss_prices[band_index]:,.2f}<br>Probability: {probabilities[band_index]:.2f}%"
                if i > 0:
                    btc_sold = btc_sold_at_each_step[i - 1]
                    if btc_sold > 0:
                        text += f"<br>BTC Sold: {btc_sold:.6f}"
                hover_text.append(text)

            # Append line data and total value
            lines.append((go.Scatter(), total_value, steps, bands, scenario, hover_text))

        # Normalize colors based on total values
        total_values = [total_value for _, total_value, _, _, _, _ in lines]
        min_total_value = min(total_values)
        max_total_value = max(total_values)
        norm = Normalize(vmin=min_total_value, vmax=max_total_value)
        cmap = cm.get_cmap('RdYlGn')

        # Create the figure
        fig = go.Figure()

        # Plot each line with appropriate color
        for line_data, total_value, steps, bands, scenario, hover_text in lines:
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
                text=hover_text,
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
        df_scenarios['Total Value Times Probability'] = df_scenarios['Total Value Times Probability'].apply(lambda x: f"${x:,.2f}")

        # Compute TOTAL SUM and TOTAL SUB PROBABILITY
        total_sum = sum([sv['Total Value'] for sv in scenario_values])
        total_sub_probability = sum([sv['Total Value Times Probability'] for sv in scenario_values])

        # Create content for totals-div
        totals_div_content = [
            html.Div(f"TOTAL SUM: ${total_sum:,.2f}", style={'fontWeight': 'bold', 'fontSize': '16px'}),
            html.Div(f"TOTAL SUM X PROBABILITY: ${total_sub_probability:,.2f}", style={'fontWeight': 'bold', 'fontSize': '16px'})
        ]

        # Compute heatmap data
        percentage_pushed_values = np.arange(0, 110, 10)  # From 0% to 100% in steps of 10%
        spreads = np.logspace(np.log10(25), 0, num=25)  # Exponential range from 1 to 20
        Z = np.zeros((len(spreads), len(percentage_pushed_values)))

        for i, spread in enumerate(spreads):
            # Compute probabilities for bands based on the spread
            N = len(band_indices)
            probabilities_spread = []
            for idx in band_indices:
                prob = max(100 - spread * (N - 1 - idx), 0)
                probabilities_spread.append(prob)
            probabilities_spread = np.array(probabilities_spread)

            for j, percentage_pushed_value in enumerate(percentage_pushed_values):
                # For each percentage_pushed, compute total sum
                scenarios = generate_risk_band_scenarios(band_indices)
                total_sum_spread = 0
                for scenario in scenarios:
                    total_value, btc_sold_at_each_step = calculate_scenario_value(scenario, stop_loss_prices, percentage_pushed_value)
                    probabilities_of_bands_in_scenario = [probabilities_spread[band_index] for band_index in scenario]
                    average_probability = sum(probabilities_of_bands_in_scenario) / len(probabilities_of_bands_in_scenario)
                    total_value_times_probability = total_value * (average_probability / 100.0)
                    total_sum_spread += total_value_times_probability
                Z[i, j] = total_sum_spread

        # Create the heatmap
        heatmap_fig = go.Figure(data=go.Heatmap(
            z=Z,
            x=percentage_pushed_values,
            y=spreads,
            colorscale='Viridis',
            showscale=False,  # This line hides the color bar
            hovertemplate='Percentage Pushed: %{x}<br>Probability Spread: %{y}<br>Total Sum X Prob: $%{z:.2f}<extra></extra>'
        ))

        heatmap_fig.update_layout(
            title='Heatmap of Total Sums',
            xaxis_title='Percentage Pushed to Next Risk Band',
            yaxis_title='Probability Spread',
            showlegend=False
        )

        # Return the figure, table data, totals content, and heatmap
        return fig, df_scenarios.to_dict('records'), totals_div_content, heatmap_fig

    @app.callback(
        [Output(f'probability-{i+1}', 'value') for i in range(num_bands)] +
        [Output('input-percentage', 'value')],
        [Input('heatmap-graph', 'clickData')],
        prevent_initial_call=True
    )
    def update_inputs_from_heatmap(clickData):
        if clickData is None:
            raise dash.exceptions.PreventUpdate
        else:
            x = clickData['points'][0]['x']  # percentage_pushed
            y = clickData['points'][0]['y']  # spread

            percentage_pushed = x

            # Compute the probabilities based on the spread
            N = num_bands
            spread = y
            probabilities = []
            for idx in range(N):
                prob = max(100 - spread * (N - 1 - idx), 0)
                probabilities.append(prob)

            # Return the new probabilities and percentage_pushed
            return probabilities + [percentage_pushed]

    # Make sure to not touch or change anything else.
