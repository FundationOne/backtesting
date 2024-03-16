import numpy as np
from datetime import datetime
import pandas as pd
from scipy.signal import find_peaks
import warnings

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
    # Slice data directly using parsed dates
    sliced_data = data.loc[start_date:end_date]

    if sliced_data.empty:
        return np.nan

    # Calculate log-transformed dates and prices
    days = np.log((sliced_data.index - sliced_data.index[0]).days + 1)
    prices = np.log((sliced_data['price'].mask(sliced_data['price'] == 0)).ffill())


    # Compute the power law exponent
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", np.RankWarning)
        try:
            # Attempt to fit the polynomial and return the first coefficient
            return np.polyfit(days, prices, 1)[0]
        except Exception as e:
            return np.nan

def rolling_power_law(btc_data):
    power_law_exponents = np.full(len(btc_data), np.nan)
    for i in range(len(btc_data)):
        power_law_exponents[i] = power_law(btc_data, btc_data.index[0], btc_data.index[i])
    return power_law_exponents
    
def power_law_price(data):
    start_price = data['price'].iloc[0]
    
    # Use numpy for vectorized operations
    days_since_start = np.arange(len(data)) + 1  # +1 to avoid log(0) for the first day
    power_law_prices = np.exp(np.log(start_price) + data['power_law_exponent'] * np.log(days_since_start))
    
    return power_law_prices

def find_support(data, window=20):
    """
    Identify simple support levels based on price troughs.
    
    :param data: Pandas Series of prices.
    :param window: Number of periods to consider for finding troughs.
    :return: Pandas Series containing support levels, with the last support value carried forward.
    """
    # Find troughs (support) in the data
    support_indices = find_peaks(-data, distance=window)[0]
    support_levels = data.iloc[support_indices]
    
    # Create a new Series to hold support levels with forward fill
    support_series = pd.Series(data=np.nan, index=data.index)
    support_series.iloc[support_indices] = support_levels.values
    support_series.ffill(inplace=True)
    
    return support_series

def find_resistance(data, window=20):
    """
    Identify simple resistance levels based on price peaks.
    
    :param data: Pandas Series of prices.
    :param window: Number of periods to consider for finding peaks.
    :return: Pandas Series containing resistance levels, with the last resistance value carried forward.
    """
    # Find peaks (resistance) in the data
    resistance_indices = find_peaks(data, distance=window)[0]
    resistance_levels = data.iloc[resistance_indices]
    
    # Create a new Series to hold resistance levels with forward fill
    resistance_series = pd.Series(data=np.nan, index=data.index)
    resistance_series.iloc[resistance_indices] = resistance_levels.values
    resistance_series.ffill(inplace=True)
    
    return resistance_series

def volume_spike_detection(volume_data, window=20, threshold=2):
    """
    Detect volume spikes and return a binary series indicating spikes.
    
    :param volume_data: Pandas Series of volume data.
    :param window: Rolling window size to calculate average volume.
    :param threshold: Multiplier to define what constitutes a spike (e.g., 2 times the average).
    :return: Pandas Series with 1 indicating a spike and 0 indicating no spike.
    """
    avg_volume = volume_data.rolling(window=window).mean()
    # Create a binary series where True (1) indicates a spike and False (0) indicates no spike
    spikes_series = (volume_data > (avg_volume * threshold)).astype(int)
    
    return spikes_series

def find_double_top(data, window=20, tolerance=0.05):
    """
    Very basic double top pattern detection.
    :param data: Pandas Series of prices.
    :param window: Number of periods to consider for identifying the pattern.
    :param tolerance: Tolerance for the price difference between the two peaks.
    :return: Indices where a double top might be forming.
    """
    potential_tops = find_peaks(data, distance=window)[0]
    double_tops = []

    for i in range(len(potential_tops)-1):
        if abs(data[potential_tops[i]] - data[potential_tops[i+1]]) / data[potential_tops[i]] < tolerance:
            double_tops.append(potential_tops[i])

    return double_tops

def fibonacci_retracement(start, end):
    """
    Calculate Fibonacci retracement levels.
    :param start: Start price of the trend.
    :param end: End price of the trend.
    :return: Dictionary with key as Fibonacci level and value as price.
    """
    levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
    retracements = {level: end - (end - start) * level for level in levels}
    return retracements

def find_head_and_shoulders(data, window=20):
    """
    Basic detection of the Head and Shoulders pattern.
    :param data: Pandas Series of prices.
    :param window: Lookback period for finding peaks.
    :return: Indices where a Head and Shoulders pattern might be forming.
    """
    peaks_indices = find_peaks(data, distance=window)[0]
    if len(peaks_indices) < 3:
        return []

    # This is a simplified logic and might need refinement
    potential_patterns = []
    for i in range(1, len(peaks_indices) - 1):
        left = peaks_indices[i - 1]
        head = peaks_indices[i]
        right = peaks_indices[i + 1]
        if data[left] < data[head] > data[right] and data[left] < data[right]:
            potential_patterns.append((left, head, right))

    return potential_patterns

def find_inverse_head_and_shoulders(data, window=20):
    """
    Basic detection of the Inverse Head and Shoulders pattern.
    :param data: Pandas Series of prices.
    :param window: Lookback period for finding troughs.
    :return: Indices where an Inverse Head and Shoulders pattern might be forming.
    """
    troughs_indices = find_peaks(-data, distance=window)[0]
    if len(troughs_indices) < 3:
        return []

    # Simplified logic
    potential_patterns = []
    for i in range(1, len(troughs_indices) - 1):
        left = troughs_indices[i - 1]
        head = troughs_indices[i]
        right = troughs_indices[i + 1]
        if data[left] > data[head] < data[right] and data[left] > data[right]:
            potential_patterns.append((left, head, right))

    return potential_patterns

def find_triple_top(data, window=20, tolerance=0.05):
    """
    Basic detection of the Triple Top pattern.
    :param data: Pandas Series of prices.
    :param window: Lookback period for finding peaks.
    :param tolerance: Tolerance for the price difference between peaks.
    :return: Indices where a Triple Top pattern might be forming.
    """
    peaks_indices = find_peaks(data, distance=window)[0]
    potential_patterns = []
    # This simplified logic checks for three peaks of similar height
    for i in range(2, len(peaks_indices)):
        if abs(data[peaks_indices[i]] - data[peaks_indices[i-1]]) / data[peaks_indices[i-1]] < tolerance \
                and abs(data[peaks_indices[i-1]] - data[peaks_indices[i-2]]) / data[peaks_indices[i-2]] < tolerance:
            potential_patterns.append((peaks_indices[i-2], peaks_indices[i-1], peaks_indices[i]))

    return potential_patterns

def find_triple_bottom(data, window=20, tolerance=0.05):
    """
    Basic detection of the Triple Bottom pattern.
    :param data: Pandas Series of prices.
    :param window: Lookback period for finding troughs.
    :param tolerance: Tolerance for the price difference between troughs.
    :return: Indices where a Triple Bottom pattern might be forming.
    """
    from scipy.signal import find_peaks
    troughs_indices = find_peaks(-data, distance=window)[0]
    potential_patterns = []
    # This simplified logic checks for three troughs of similar depth
    for i in range(2, len(troughs_indices)):
        if abs(data[troughs_indices[i]] - data[troughs_indices[i-1]]) / data[troughs_indices[i-1]] < tolerance \
                and abs(data[troughs_indices[i-1]] - data[troughs_indices[i-2]]) / data[troughs_indices[i-2]] < tolerance:
            potential_patterns.append((troughs_indices[i-2], troughs_indices[i-1], troughs_indices[i]))

    return potential_patterns

