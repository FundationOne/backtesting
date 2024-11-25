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

# Define scenario descriptions
scenario_descriptions = {
    'Scenario 1': 'Price remains at Level A. (A → A → A → A → A → A)',
    'Scenario 2': 'Consistently rising prices. (A → B → C → D → E → E)',
    'Scenario 3': 'Consistently falling prices. (A → B → C → D → E → A)',
    'Scenario 4': 'Fluctuating prices between Level A and B. (A → B → A → B → A → B)',
    'Scenario 5': 'Fluctuating with higher peaks at Level C. (A → C → A → C → A → C)',
    'Scenario 6': 'Delayed rise in prices. (A → A → B → B → C → C)',
    'Scenario 7': 'Early rise to Level D then plateau. (A → D → D → D → D → D)',
    'Scenario 8': 'Rising prices with minor dips. (A → B → C → B → C → D)',
    'Scenario 9': 'Late rise to Level B. (A → A → A → B → B → B)',
    'Scenario 10': 'Peak at Level E then slight drop. (A → B → C → D → E → D)',
    'Scenario 11': 'Peak at Level E then fall to initial. (A → B → C → D → E → A)',
    'Scenario 12': 'Immediate peak at Level E. (A → E → E → E → E → E)',
    'Scenario 13': 'Sudden spike at the end. (A → A → A → A → A → E)',
    'Scenario 14': 'Fluctuating with higher highs. (A → B → A → C → A → D)',
    'Scenario 15': 'Fluctuating between Level A and D. (A → D → A → D → A → D)',
    'Scenario 16': 'Price remains at Level B. (A → B → B → B → B → B)',
    'Scenario 17': 'Rise then fall then rise again. (A → B → C → B → A → B)',
    'Scenario 18': 'Fluctuating with overall rise. (A → C → B → D → C → E)',
    'Scenario 19': 'Drop before final rise to Level E. (A → D → C → B → A → E)',
    'Scenario 20': 'Late peaks with drops. (A → A → B → A → C → A)'
}

# Define scenarios
scenarios = {
    'Scenario 1': ['A', 'A', 'A', 'A', 'A', 'A'],
    'Scenario 2': ['A', 'B', 'C', 'D', 'E', 'E'],
    'Scenario 3': ['A', 'B', 'C', 'D', 'E', 'A'],
    'Scenario 4': ['A', 'B', 'A', 'B', 'A', 'B'],
    'Scenario 5': ['A', 'C', 'A', 'C', 'A', 'C'],
    'Scenario 6': ['A', 'A', 'B', 'B', 'C', 'C'],
    'Scenario 7': ['A', 'D', 'D', 'D', 'D', 'D'],
    'Scenario 8': ['A', 'B', 'C', 'B', 'C', 'D'],
    'Scenario 9': ['A', 'A', 'A', 'B', 'B', 'B'],
    'Scenario 10': ['A', 'B', 'C', 'D', 'E', 'D'],
    'Scenario 11': ['A', 'B', 'C', 'D', 'E', 'A'],
    'Scenario 12': ['A', 'E', 'E', 'E', 'E', 'E'],
    'Scenario 13': ['A', 'A', 'A', 'A', 'A', 'E'],
    'Scenario 14': ['A', 'B', 'A', 'C', 'A', 'D'],
    'Scenario 15': ['A', 'D', 'A', 'D', 'A', 'D'],
    'Scenario 16': ['A', 'B', 'B', 'B', 'B', 'B'],
    'Scenario 17': ['A', 'B', 'C', 'B', 'A', 'B'],
    'Scenario 18': ['A', 'C', 'B', 'D', 'C', 'E'],
    'Scenario 19': ['A', 'D', 'C', 'B', 'A', 'E'],
    'Scenario 20': ['A', 'A', 'B', 'A', 'C', 'A']
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
            html.H4("Number of Simulations"),
            dbc.Input(id='num-simulations', type='number', value=1000, min=100, step=100, className="mb-2"),
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
    levels = ['A', 'B', 'C', 'D', 'E']
    cum_probs = [cumulative_probabilities[level] for level in levels]
    marginal_probs['E'] = cum_probs[-1] / 100
    for i in range(len(levels)-2, -1, -1):
        marginal_probs[levels[i]] = (cum_probs[i] - cum_probs[i+1]) / 100

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

    # Initialize variables for scenario results
    scenario_results = []
    strategy_summary = {strategy: {'Winning Scenarios': [], 'Total BTC Sold': []} for strategy in strategies}

    # Process predefined scenarios
    for scenario_name, price_path in scenarios.items():
        print(scenario_name)
        prices = [price_levels[point] for point in price_path]
        results = []

        for strategy in strategies:
            btc_remaining = 1.0
            cash_received = 0.0
            actions = []
            goal_achieved = False

            # Implement Strategy 1
            if strategy == 'Strategy 1':
                sell_price = prices[0]
                btc_to_sell = min(btc_remaining, 80000 / sell_price)
                cash = btc_to_sell * sell_price
                btc_remaining -= btc_to_sell
                cash_received += cash
                actions.append(f"Sold {btc_to_sell:.4f} BTC at ${sell_price}")
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
                        actions.append(f"Sold {btc_to_sell:.4f} BTC at ${sell_price}")
                        goal_achieved = cash_received >= 80000
                        break
                    elif price <= stop_loss_price and not stop_loss_triggered:
                        sell_price = stop_loss_price
                        btc_to_sell = btc_remaining
                        cash = btc_to_sell * sell_price
                        btc_remaining = 0
                        cash_received += cash
                        actions.append(f"Stop-loss triggered. Sold {btc_to_sell:.4f} BTC at ${sell_price}")
                        goal_achieved = cash_received >= 80000
                        break

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
                        actions.append(f"Sold {btc_to_sell:.4f} BTC at ${sell_price}")
                        if cash_received >= 80000:
                            goal_achieved = True
                            break
                    if price <= stop_loss_price and not stop_loss_triggered:
                        sell_price = stop_loss_price
                        btc_to_sell = btc_remaining
                        cash = btc_to_sell * sell_price
                        btc_remaining = 0
                        cash_received += cash
                        actions.append(f"Stop-loss triggered. Sold {btc_to_sell:.4f} BTC at ${sell_price}")
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
                    actions.append(f"Final sale of {btc_to_sell:.4f} BTC at ${sell_price}")
                    goal_achieved = cash_received >= 80000

            # Implement Strategy 4
            elif strategy == 'Strategy 4':
                sell_price = prices[-1]
                btc_to_sell = min(btc_remaining, 80000 / sell_price)
                cash = btc_to_sell * sell_price
                btc_remaining -= btc_to_sell
                cash_received += cash
                actions.append(f"Sold {btc_to_sell:.4f} BTC at ${sell_price}")
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
                        actions.append(f"Trailing stop-loss triggered. Sold {btc_to_sell:.4f} BTC at ${sell_price:.2f}")
                        goal_achieved = cash_received >= 80000
                        break
                else:
                    # If stop-loss not triggered, sell at last price
                    sell_price = prices[-1]
                    btc_to_sell = btc_remaining
                    cash = btc_to_sell * sell_price
                    btc_remaining = 0
                    cash_received += cash
                    actions.append(f"Sold {btc_to_sell:.4f} BTC at ${sell_price}")
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
                        actions.append(f"Sold {btc_to_sell:.4f} BTC at ${sell_price}")
                        goal_achieved = cash_received >= 80000
                        break
                else:
                    # If target price not reached, sell at last price
                    sell_price = prices[-1]
                    btc_to_sell = min(btc_remaining, 80000 / sell_price)
                    cash = btc_to_sell * sell_price
                    btc_remaining -= btc_to_sell
                    cash_received += cash
                    actions.append(f"Target not reached. Sold {btc_to_sell:.4f} BTC at ${sell_price}")
                    goal_achieved = cash_received >= 80000

            # Record the result
            total_btc_sold = round(1.0 - btc_remaining, 4)
            result = {
                'Strategy': strategy,
                'Actions': '; '.join(actions),
                'Total BTC Sold': total_btc_sold,
                'Cash Received': cash_received,
                'Goal Achieved': 'Yes' if goal_achieved else 'No'
            }
            results.append(result)

            # Update strategy summary
            # if goal_achieved:
            #     strategy_summary[strategy]['Winning Scenarios'].append(scenario_name)
            #     strategy_summary[strategy]['Total BTC Sold'].append(total_btc_sold)

        # Convert results to DataFrame
        df_results = pd.DataFrame(results)
        df_results['Total BTC Sold'] = df_results['Total BTC Sold'].astype(float)
        df_results['Cash Received'] = df_results['Cash Received'].astype(float)

        # Determine the winning strategy (least BTC sold, goal achieved)
        goal_achieved_df = df_results[df_results['Goal Achieved'] == 'Yes']
        if not goal_achieved_df.empty:
            min_btc_sold = goal_achieved_df['Total BTC Sold'].min()
            df_results['Winner'] = df_results.apply(
                lambda x: 'Yes' if x['Goal Achieved'] == 'Yes' and x['Total BTC Sold'] == min_btc_sold else '', axis=1
            )
        else:
            df_results['Winner'] = ''

        # Update strategy summary based on the winning strategy/strategies
        winning_strategies = df_results[df_results['Winner'] == 'Yes']['Strategy'].tolist()
        for winning_strategy in winning_strategies:
            strategy_summary[winning_strategy]['Winning Scenarios'].append(scenario_name)
            # Get the Total BTC Sold for the winning strategy
            total_btc_sold = df_results[df_results['Strategy'] == winning_strategy]['Total BTC Sold'].values[0]
            strategy_summary[winning_strategy]['Total BTC Sold'].append(total_btc_sold)
            
        # Append scenario description
        df_results.insert(0, 'Scenario', scenario_name)
        df_results.insert(1, 'Scenario Description', scenario_descriptions[scenario_name])

        # Append to the list
        scenario_results.append(df_results)

    # Process simulations using probabilities
    # Initialize strategy results
    sim_strategy_results = {strategy: {'Cash Received': [], 'Goal Achieved': [], 'Total BTC Sold': []} for strategy in strategies}

    for price_path in price_paths:
        prices = [price_levels[level] for level in price_path]

        for strategy in strategies:
            btc_remaining = 1.0
            cash_received = 0.0
            goal_achieved = False

            # Implement Strategy 1
            if strategy == 'Strategy 1':
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
            sim_strategy_results[strategy]['Cash Received'].append(cash_received)
            sim_strategy_results[strategy]['Goal Achieved'].append(goal_achieved)
            sim_strategy_results[strategy]['Total BTC Sold'].append(total_btc_sold)

    # Create strategy summary table
    summary_rows = []
    for strategy in strategies:
        # Results from predefined scenarios
        num_wins = len(strategy_summary[strategy]['Winning Scenarios'])
        avg_btc_sold_scenarios = round(sum(strategy_summary[strategy]['Total BTC Sold']) / num_wins, 4) if num_wins > 0 else 'N/A'

        # Results from simulations
        cash_received_list = sim_strategy_results[strategy]['Cash Received']
        goal_achieved_list = sim_strategy_results[strategy]['Goal Achieved']
        total_btc_sold_list = sim_strategy_results[strategy]['Total BTC Sold']

        avg_cash_received = np.mean(cash_received_list)
        prob_goal_achieved = np.mean(goal_achieved_list)
        avg_btc_sold_simulations = np.mean(total_btc_sold_list)

        summary_rows.append({
            'Strategy': strategy,
            'Description': strategies[strategy],
            'Number of Wins in Scenarios': num_wins,
            'Winning Scenarios': ', '.join(strategy_summary[strategy]['Winning Scenarios']),
            'Avg BTC Sold in Scenario Wins': avg_btc_sold_scenarios,
            'Expected Cash Received (Simulations)': f"${avg_cash_received:,.2f}",
            'Probability of Achieving Goal (Simulations)': f"{prob_goal_achieved * 100:.2f}%",
            'Avg BTC Sold (Simulations)': f"{avg_btc_sold_simulations:.4f}"
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

    # Display results
    tables = []
    for df in scenario_results:
        scenario_name = df['Scenario'].iloc[0]
        description = df['Scenario Description'].iloc[0]
        table = dash_table.DataTable(
            columns=[{"name": i, "id": i} for i in df.columns if i not in ['Scenario', 'Scenario Description']],
            data=df.to_dict('records'),
            style_cell={
                'textAlign': 'left',
                'whiteSpace': 'normal',
                'height': 'auto',
                'minWidth': '100px',
                'width': '150px',
                'maxWidth': '300px',
            },
            style_header={
                'backgroundColor': 'rgb(230, 230, 230)',
                'fontWeight': 'bold'
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{Winner} = "Yes"'},
                    'backgroundColor': '#C2FFC2'
                },
                {
                    'if': {'filter_query': '{Goal Achieved} = "No"'},
                    'backgroundColor': '#FFC2C2'
                },
            ]
        )
        tables.append(html.H4(f"{scenario_name}: {description}"))
        tables.append(table)
        tables.append(html.Hr())

    # Append simulation results
    tables.append(html.H2("Simulation Results"))
    tables.append(html.P("The simulation results are based on the selected probability set and number of simulations."))

    return html.Div([
        html.H2("Strategy Summary"),
        summary_table,
        html.Hr()
    ]), tables

if __name__ == '__main__':
    app.run_server(debug=True)
