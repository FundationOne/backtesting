# app.py

import dash
from dash import dcc, html, dash_table, Input, Output, State
import pandas as pd
import dash_bootstrap_components as dbc
import numpy as np

# Initialize the Dash app with Bootstrap CSS for better styling
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Define default price levels
default_price_levels = {
    'A': 97000,
    'B': 110800,
    'C': 137200,
    'D': 166900,
    'E': 196900
}

# Define improved predefined cumulative probability sets
probability_sets = {
    'Equal Probabilities': {'A': 100, 'B': 80, 'C': 60, 'D': 40, 'E': 20},
    'Bullish Market': {'A': 100, 'B': 90, 'C': 70, 'D': 50, 'E': 30},
    'Bearish Market': {'A': 100, 'B': 60, 'C': 30, 'D': 10, 'E': 5},
    'Volatile Market': {'A': 100, 'B': 70, 'C': 50, 'D': 30, 'E': 15},
    'Pessimistic Market': {'A': 100, 'B': 50, 'C': 25, 'D': 10, 'E': 1}
}

# Define strategies
strategies = {
    'Strategy 1': 'Sell immediately at the current price (Price Level A) to secure $80,000. This conservative approach avoids market risks by cashing out as soon as possible.',

    'Strategy 2': 'Hold off on selling until the price reaches at least Price Level B, but employ a stop-loss at $87,600 to mitigate risk. This balances the potential for higher gains with protection against significant losses if the price drops below the stop-loss threshold.',

    'Strategy 3': 'Sell incrementally at predefined levels (A, B, and C), with a portion (0.2 BTC) sold at each level. A stop-loss at $87,600 ensures protection against sudden downturns. If the goal is not met after all planned sales, sell the remaining BTC at the last price to reach $80,000.',

    'Strategy 4': 'Hold all BTC until the last price point and sell enough at that final price to secure $80,000. This high-risk, high-reward approach relies entirely on market conditions at the end of the period, with no stop-loss protection.',

    'Strategy 5': 'Utilize a trailing stop-loss set 10% below the highest price reached. As the price rises, the stop-loss adjusts upward to lock in potential gains. If the price falls by 10% from the peak, sell all BTC. If the stop-loss is not triggered, sell all BTC at the last price.',

    'Strategy 6': 'Wait for the price to reach at least Price Level C before selling. If Price Level C is not reached, sell at the last price point to meet the $80,000 goal. This strategy prioritizes higher returns but risks missing the goal entirely if the target price is not reached.'
}

# Layout of the app
app.layout = dbc.Container([
    html.H1("Bitcoin Strategy Analysis", className="my-4"),
    dbc.Row([
        dbc.Col([
            html.H4("Enter Price Levels"),
            dbc.Form([
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level A:", html_for='price-A'), width=4),
                    dbc.Col(dbc.Input(id='price-A', type='number', value=default_price_levels['A'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level B:", html_for='price-B'), width=4),
                    dbc.Col(dbc.Input(id='price-B', type='number', value=default_price_levels['B'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level C:", html_for='price-C'), width=4),
                    dbc.Col(dbc.Input(id='price-C', type='number', value=default_price_levels['C'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level D:", html_for='price-D'), width=4),
                    dbc.Col(dbc.Input(id='price-D', type='number', value=default_price_levels['D'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level E:", html_for='price-E'), width=4),
                    dbc.Col(dbc.Input(id='price-E', type='number', value=default_price_levels['E'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
            ], className="mb-4"),
        ], md=6),
        dbc.Col([
            html.H4("Select Probability Set"),
            dcc.Dropdown(
                id='probability-set-dropdown',
                options=[{'label': key, 'value': key} for key in probability_sets.keys()],
                value='Equal Probabilities',
                clearable=False,
            ),
            html.Div(id='probabilities-display', className="mt-3"),
        ], md=6),
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Label("Number of Simulations:", html_for='num-simulations'),
            dbc.Input(id='num-simulations', type='number', value=1000, min=100, max=10000, step=100, className="mb-4"),
        ], md=6),
    ]),
    dbc.Button('Run Analysis', id='run-button', color='primary', className="my-4"),
    html.Div(id='summary-table'),
    html.Div(id='results-div')
], fluid=True)

# Callback to display selected probabilities
@app.callback(
    Output('probabilities-display', 'children'),
    Input('probability-set-dropdown', 'value')
)
def display_probabilities(selected_set):
    probs = probability_sets[selected_set]
    return html.Div([
        html.P("Selected Cumulative Probabilities (Probability of reaching at least this level):"),
        html.Ul([html.Li(f"Price Level {level}: {prob}%") for level, prob in probs.items()])
    ])

# Callback to run analysis and display results
@app.callback(
    [Output('summary-table', 'children'),
     Output('results-div', 'children')],
    Input('run-button', 'n_clicks'),
    State('price-A', 'value'),
    State('price-B', 'value'),
    State('price-C', 'value'),
    State('price-D', 'value'),
    State('price-E', 'value'),
    State('probability-set-dropdown', 'value'),
    State('num-simulations', 'value'),
)
def run_analysis(n_clicks, price_A, price_B, price_C, price_D, price_E, selected_prob_set, num_simulations):
    if n_clicks is None:
        return '', ''

    # Update price levels and probabilities
    price_levels = {
        'A': price_A,
        'B': price_B,
        'C': price_C,
        'D': price_D,
        'E': price_E
    }
    cumulative_probabilities = probability_sets[selected_prob_set]

    # Compute marginal probabilities
    marginal_probs = {}
    marginal_probs['A'] = (100 - cumulative_probabilities['B']) / 100
    marginal_probs['B'] = (cumulative_probabilities['B'] - cumulative_probabilities['C']) / 100
    marginal_probs['C'] = (cumulative_probabilities['C'] - cumulative_probabilities['D']) / 100
    marginal_probs['D'] = (cumulative_probabilities['D'] - cumulative_probabilities['E']) / 100
    marginal_probs['E'] = cumulative_probabilities['E'] / 100

    levels = ['A', 'B', 'C', 'D', 'E']
    probabilities = [marginal_probs[level] for level in levels]

    # Number of periods (time points)
    num_periods = 6

    # Number of simulations
    N = num_simulations

    # Simulate price paths
    price_paths = []
    for _ in range(N):
        price_path = np.random.choice(levels, size=num_periods, p=probabilities)
        price_paths.append(price_path)

    # Initialize strategy results
    strategy_results = {strategy: {'Cash Received': [], 'Goal Achieved': [], 'Total BTC Sold': []} for strategy in strategies}

    for price_path in price_paths:
        prices = [price_levels[level] for level in price_path]

        for strategy in strategies:
            btc_remaining = 1.0
            cash_received = 0.0
            goal_achieved = False

            # Implement Strategy 1
            if strategy == 'Strategy 1':
                # Sell immediately at current price
                sell_price = prices[0]
                btc_to_sell = min(btc_remaining, 80000 / sell_price)
                cash = btc_to_sell * sell_price
                btc_remaining -= btc_to_sell
                cash_received += cash
                goal_achieved = cash_received >= 80000

            # Implement Strategy 2
            elif strategy == 'Strategy 2':
                stop_loss_price = 87600
                stop_loss_triggered = False
                for price in prices:
                    if price >= price_levels['B']:
                        sell_price = price
                        btc_to_sell = min(btc_remaining, 80000 / sell_price)
                        cash = btc_to_sell * sell_price
                        btc_remaining -= btc_to_sell
                        cash_received += cash
                        goal_achieved = cash_received >= 80000
                        break
                    elif price <= stop_loss_price and not stop_loss_triggered:
                        sell_price = stop_loss_price
                        btc_to_sell = btc_remaining
                        cash = btc_to_sell * sell_price
                        btc_remaining = 0
                        cash_received += cash
                        goal_achieved = cash_received >= 80000
                        break
                else:
                    # If neither condition met, sell at last price
                    if btc_remaining > 0:
                        sell_price = prices[-1]
                        btc_to_sell = btc_remaining
                        cash = btc_to_sell * sell_price
                        btc_remaining = 0
                        cash_received += cash
                        goal_achieved = cash_received >= 80000

            # Implement Strategy 3
            elif strategy == 'Strategy 3':
                sell_points = [price_levels['A'], price_levels['B'], price_levels['C']]
                btc_per_sale = 0.2
                stop_loss_price = 87600
                stop_loss_triggered = False
                for price in prices:
                    if price in sell_points and btc_remaining >= btc_per_sale:
                        sell_price = price
                        btc_to_sell = min(btc_per_sale, btc_remaining)
                        cash = btc_to_sell * sell_price
                        btc_remaining -= btc_to_sell
                        cash_received += cash
                        if cash_received >= 80000:
                            goal_achieved = True
                            break
                    if price <= stop_loss_price and not stop_loss_triggered:
                        sell_price = stop_loss_price
                        btc_to_sell = btc_remaining
                        cash = btc_to_sell * sell_price
                        btc_remaining = 0
                        cash_received += cash
                        goal_achieved = cash_received >= 80000
                        break
                # Final sale if goal not achieved
                if not goal_achieved and btc_remaining > 0:
                    sell_price = prices[-1]
                    btc_needed = (80000 - cash_received) / sell_price
                    btc_to_sell = min(btc_remaining, btc_needed)
                    cash = btc_to_sell * sell_price
                    btc_remaining -= btc_to_sell
                    cash_received += cash
                    goal_achieved = cash_received >= 80000

            # Implement Strategy 4
            elif strategy == 'Strategy 4':
                sell_price = prices[-1]
                btc_to_sell = min(btc_remaining, 80000 / sell_price)
                cash = btc_to_sell * sell_price
                btc_remaining -= btc_to_sell
                cash_received += cash
                goal_achieved = cash_received >= 80000

            # Implement Strategy 5
            elif strategy == 'Strategy 5':
                trailing_percentage = 0.10
                peak_price = prices[0]
                for price in prices:
                    if price > peak_price:
                        peak_price = price
                    stop_price = peak_price * (1 - trailing_percentage)
                    if price <= stop_price:
                        sell_price = stop_price
                        btc_to_sell = btc_remaining
                        cash = btc_to_sell * sell_price
                        btc_remaining = 0
                        cash_received += cash
                        goal_achieved = cash_received >= 80000
                        break
                else:
                    # If stop-loss not triggered, sell at last price
                    if btc_remaining > 0:
                        sell_price = prices[-1]
                        btc_to_sell = btc_remaining
                        cash = btc_to_sell * sell_price
                        btc_remaining = 0
                        cash_received += cash
                        goal_achieved = cash_received >= 80000

            # Implement Strategy 6
            elif strategy == 'Strategy 6':
                target_price = price_levels['C']
                for price in prices:
                    if price >= target_price:
                        sell_price = price
                        btc_to_sell = min(btc_remaining, 80000 / sell_price)
                        cash = btc_to_sell * sell_price
                        btc_remaining -= btc_to_sell
                        cash_received += cash
                        goal_achieved = cash_received >= 80000
                        break
                else:
                    # If target price not reached, sell at last price
                    if btc_remaining > 0:
                        sell_price = prices[-1]
                        btc_to_sell = min(btc_remaining, 80000 / sell_price)
                        cash = btc_to_sell * sell_price
                        btc_remaining -= btc_to_sell
                        cash_received += cash
                        goal_achieved = cash_received >= 80000

            # Record the result
            total_btc_sold = 1.0 - btc_remaining
            strategy_results[strategy]['Cash Received'].append(cash_received)
            strategy_results[strategy]['Goal Achieved'].append(goal_achieved)
            strategy_results[strategy]['Total BTC Sold'].append(total_btc_sold)

    # Create strategy summary table
    summary_rows = []
    for strategy in strategies:
        cash_received_list = strategy_results[strategy]['Cash Received']
        goal_achieved_list = strategy_results[strategy]['Goal Achieved']
        total_btc_sold_list = strategy_results[strategy]['Total BTC Sold']

        avg_cash_received = np.mean(cash_received_list)
        prob_goal_achieved = np.mean(goal_achieved_list)
        avg_btc_sold = np.mean(total_btc_sold_list)

        summary_rows.append({
            'Strategy': strategy,
            'Description': strategies[strategy],
            'Expected Cash Received': f"${avg_cash_received:,.2f}",
            'Probability of Achieving Goal': f"{prob_goal_achieved * 100:.2f}%",
            'Average BTC Sold': f"{avg_btc_sold:.4f}"
        })

    df_summary = pd.DataFrame(summary_rows)

    # Create Dash table for summary
    summary_table = dash_table.DataTable(
        columns=[{"name": i, "id": i} for i in df_summary.columns],
        data=df_summary.to_dict('records'),
        style_cell={
            'textAlign': 'left',
            'whiteSpace': 'normal',
            'height': 'auto',
            'minWidth': '150px',
            'width': '200px',
            'maxWidth': '300px',
        },
        style_header={
            'backgroundColor': 'rgb(230, 230, 230)',
            'fontWeight': 'bold'
        },
    )

    # Display results (optional)
    results_div = html.Div([
        html.H2("Simulation Results"),
        html.P("Detailed results are not displayed for brevity.")
    ])

    return html.Div([
        html.H2("Strategy Summary"),
        summary_table,
        html.Hr()
    ]), results_div

if __name__ == '__main__':
    app.run_server(debug=True)
