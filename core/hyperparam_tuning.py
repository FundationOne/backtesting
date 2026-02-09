import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit, cross_val_score, train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from dash.exceptions import PreventUpdate
from dash import dcc, html, ctx
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State, MATCH, ALL, ALLSMALLER
import optuna
import plotly.graph_objs as go
import joblib
import json
from multiprocessing import Pool
from core.conf import PREPROC_FILENAME

# Load the data
btc_data = pd.read_csv(PREPROC_FILENAME, parse_dates=['Date'], index_col='Date')
print(f"Hyperparam data loaded from {PREPROC_FILENAME}.")

# Define available features
available_features = btc_data.columns.tolist()

# Define the hyperparameter tuning function using optuna
def tune_hyperparameters(X_train, y_train, n_jobs=-1):
    def objective(trial, X_train, y_train):
        max_depth = trial.suggest_int("max_depth", 3, 10)
        num_leaves = trial.suggest_int("num_leaves", 31, 255)
        learning_rate = trial.suggest_float("learning_rate", 1e-3, 1e-1, log=True)

        params = {
            "max_depth": max_depth,
            "num_leaves": num_leaves,
            "learning_rate": learning_rate,
        }

        model = lgb.LGBMRegressor(**params)
        scores = cross_val_score(model, X_train, y_train, scoring="neg_mean_squared_error", cv=TimeSeriesSplit(n_splits=5), n_jobs=n_jobs)
        avg_score = -scores.mean()

        return avg_score

    sampler = optuna.samplers.TPESampler(seed=42)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.optimize(lambda trial: objective(trial, X_train, y_train), n_trials=100, n_jobs=n_jobs)

    best_params = study.best_params
    return best_params

# Define the layout
layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader("Select Features and Lags"),
                            dbc.CardBody(
                                [
                                    dcc.Store(id='features-store', data=[]),  # Stores the features list
                                    html.Label("Features", htmlFor="feature-input"),
                                    dbc.Row([
                                        dbc.Col([
                                            dbc.Input(id='feature-input', type='text', placeholder='Enter a feature...'),
                                        ], width="auto"),
                                        dbc.Col([
                                            dbc.Button('Add Feature', id='add-feature-btn'),
                                        ], width="auto"),
                                    ], className="mb-3", justify="start"),
                                    dbc.ListGroup(id='features-list', className="mb-3"),
                                    html.Label("Lags to use", htmlFor="lag-input"),
                                    dbc.Row([
                                        dbc.Col([
                                            dbc.Input(
                                                id="lag-input",
                                                type="text",
                                                placeholder="Enter lag(s) separated by commas",
                                            ),
                                        ], width="auto"),
                                    ], className="mb-3", justify="start"),
                                    html.Label("Prediction Horizon", htmlFor="prediction-horizon"),
                                    dbc.Row([
                                        dbc.Col([
                                            dbc.Input(
                                                id="prediction-horizon",
                                                type="number",
                                                placeholder="Enter number of days (e.g., 1 for tomorrow)",
                                                value=1,
                                                min=1,
                                            ),
                                        ], width="auto"),
                                    ], className="mb-3", justify="start"),
                                    dbc.Button(
                                        "Begin Training",
                                        id="train-button",
                                        color="primary",
                                        className="mt-3",
                                    ),
                                ]
                            ),
                        ]
                    ),
                    width=4,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader("Prediction"),
                            dbc.CardBody(
                                [
                                    dcc.Loading(
                                        id="prediction-loading",
                                        children=[
                                            dcc.Graph(id="prediction-graph",\n                                                     config={\"displayModeBar\": False, \"displaylogo\": False}),
                                            dbc.Card(
                                                [
                                                    dbc.CardHeader("Evaluation Metrics"),
                                                    dbc.CardBody(
                                                        [
                                                            html.Div(id="evaluation-metrics"),
                                                        ]
                                                    ),
                                                ],
                                                className="mt-3",
                                            ),
                                        ],
                                        type="default",
                                    ),
                                ]
                            ),
                        ]
                    ),
                    width=8,
                ),
            ]
        ),
    ],
    fluid=True,
)

# Define the callbacks

def register_callbacks(app):
    @app.callback(
        Output('features-store', 'data', allow_duplicate=True),
        Input('add-feature-btn', 'n_clicks'),
        State('feature-input', 'value'),
        State('features-store', 'data'),
        prevent_initial_call=True
    )
    def add_feature(n_clicks, feature, features):
        if feature:  # Ensure the feature is not empty
            features.append(feature)  # Add the new feature to the list
        return features  # Update the store with the new list

    # Callback to display the features list and include a remove button for each item
    @app.callback(
        Output('features-list', 'children'),
        Input('features-store', 'data')
    )
    def update_features_list(features):
        list_items = []
        for i, feature in enumerate(features):
            # Each list item has a feature and a button to remove it
            item = dbc.ListGroupItem([
                html.Span(feature),
                dbc.Button('Remove', id={'type': 'remove-feature-btn', 'index': i}, className="ms-2", color="danger", size="sm")
            ])
            list_items.append(item)
        return list_items

    # Callback to handle the removal of a feature
    @app.callback(
        Output('features-store', 'data'),
        [Input({'type': 'remove-feature-btn', 'index': ALL}, 'n_clicks')],
        [State('features-store', 'data')]
    )
    def remove_feature(n_clicks, features):
        if not ctx.triggered:
            return features

        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
        index_to_remove = json.loads(button_id)['index']  # Extract the index of the button that was clicked

        # Remove the feature at the specified index
        if features and 0 <= index_to_remove < len(features):
            features.pop(index_to_remove)

        return features  # Update the store with the modified list
    
    @app.callback(
        Output("lag-modal", "is_open"),
        Input({"type": "tag", "index": ALL}, "n_clicks"),
        State("lag-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_lag_modal(n_clicks, is_open):
        if any(n_clicks):
            return not is_open
        return is_open

    @app.callback(
        Output("features-store", "data", allow_duplicate=True),
        Input("save-lags", "n_clicks"),
        State("lag-input", "value"),
        State("features-store", "data"),
        prevent_initial_call=True,
    )
    def update_selected_features_with_lags(n_clicks, lags, current_values):
        if n_clicks:
            updated_values = []
            for feat in current_values:
                feat_with_lags = f"{feat}"
                for lag in lags.split(','):
                    feat_with_lags += f"_lag{lag.strip()}"
                updated_values.append(feat_with_lags)
            return updated_values
        return current_values

    @app.callback(
        Output("prediction-graph", "figure"),
        Output("evaluation-metrics", "children"),
        Input("train-button", "n_clicks"),
        State("features-store", "value"),
        State("lag-input", "value"),
        State("prediction-horizon", "value"),
    )
    def train_and_predict(n_clicks, selected_features, lags, prediction_horizon):
        if n_clicks is None:
            raise PreventUpdate
        
        selected_features = [feature["props"]["children"] for feature in selected_features]

        # Prepare the data
        X = btc_data[selected_features]
        for feature in selected_features:
            for lag in lags:
                X[f"{feature}_lag{lag}"] = X[feature].shift(int(lag))

        y = btc_data["price"].shift(-prediction_horizon)  # Shift the target variable for prediction
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

        # Hyperparameter tuning
        with Pool() as pool:
            best_params = tune_hyperparameters(X_train, y_train, n_jobs=pool._processes)

        # Train the model with the best hyperparameters
        model = lgb.LGBMRegressor(**best_params)
        model.fit(X_train, y_train)

        # Make predictions
        y_pred = model.predict(X_test)

        # Calculate evaluation metrics
        mse = mean_squared_error(y_test, y_pred)
        rmse = mean_squared_error(y_test, y_pred, squared=False)
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)

        # Save the best hyperparameters to a CSV file
        best_params_df = pd.DataFrame([best_params])
        best_params_df.to_csv("best_params.csv", index=False)

        # Save the trained model
        joblib.dump(model, "trained_model.joblib")

        # Plot the predictions
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=y_test.index, y=y_test, mode="lines", name="Actual"))
        fig.add_trace(go.Scatter(x=y_test.index, y=y_pred, mode="lines", name="Predicted"))
        fig.update_layout(title="Bitcoin Price Prediction", xaxis_title="Date", yaxis_title="Price")

        # Display evaluation metrics
        metrics_text = [
            html.H6("Mean Squared Error (MSE): {:.4f}".format(mse)),
            html.H6("Root Mean Squared Error (RMSE): {:.4f}".format(rmse)),
            html.H6("Mean Absolute Error (MAE): {:.4f}".format(mae)),
            html.H6("R-squared (R²): {:.4f}".format(r2)),
        ]

        return fig, metrics_text