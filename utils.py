import numpy as np
from datetime import datetime

# Assuming the halving dates are known
halving_dates = [
    datetime(2012, 11, 28),
    datetime(2016, 7, 9),
    datetime(2020, 5, 11),
    datetime(2024, 5, 23)  # Projected date for the next halving
]

def days_since_last_halving(date):
    for i in range(len(halving_dates) - 1, -1, -1):
        if date >= halving_dates[i]:
            return (date - halving_dates[i]).days
    return None

def power_law(data, start_date, end_date):
    start_index = data.index.get_loc(start_date)
    end_index = data.index.get_loc(end_date)
    dates = np.array([(data.index[i] - data.index[start_index]).days for i in range(start_index, end_index + 1)])
    prices = data['Price'].values[start_index:end_index + 1]
    coefficients = np.polyfit(np.log(dates), np.log(prices), 1)
    return coefficients[0]  # Return the power law exponent

def price_power_law_relation(data, start_date, end_date):
    power_law_exponent = power_law(data, start_date, end_date)
    start_index = data.index.get_loc(start_date)
    end_index = data.index.get_loc(end_date)
    dates = np.array([(data.index[i] - data.index[start_index]).days for i in range(start_index, end_index + 1)])
    prices = data['Price'].values[start_index:end_index + 1]
    power_law_prices = np.exp(np.log(prices[0]) + power_law_exponent * np.log(dates))
    return prices / power_law_prices