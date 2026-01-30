"""
Performance Calculation Module
Handles Time-Weighted Return (TWR), drawdown, and other performance metrics.

This module provides a clean, reusable API for performance calculations
that can be used across the application (TR sync, chart rendering, etc.)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import logging

log = logging.getLogger(__name__)


def calculate_twr_series(
    values: List[float],
    invested: List[float],
) -> List[float]:
    """Calculate Time-Weighted Return series.
    
    TWR chains period returns to exclude the effect of cash flows.
    Formula: For each period, calculate (end_value - cash_flow) / start_value - 1
    Then chain: cumulative_twr = product(1 + period_return) - 1
    
    Args:
        values: List of portfolio values at each date
        invested: List of invested (cost basis) amounts at each date
        
    Returns:
        List of TWR percentages (same length as inputs), starting at 0%
    """
    if len(values) < 2:
        return [0.0] * len(values)
    
    values = np.array(values, dtype=float)
    invested = np.array(invested, dtype=float)
    
    twr_cumulative = [0.0]  # Always start at 0%
    cumulative_factor = 1.0
    
    for i in range(1, len(values)):
        prev_value = values[i-1]
        curr_value = values[i]
        cash_flow = invested[i] - invested[i-1]  # Change in invested = cash flow
        
        if prev_value > 0 and np.isfinite(prev_value):
            # Period return = (end_value - cash_flow) / start_value - 1
            # This removes the effect of the cash flow on the return
            adjusted_end = curr_value - cash_flow
            period_return = (adjusted_end / prev_value) - 1
            
            # Clamp extreme values to avoid chart issues
            period_return = max(-0.99, min(period_return, 10.0))
            
            cumulative_factor *= (1 + period_return)
        
        twr_cumulative.append((cumulative_factor - 1) * 100)
    
    return twr_cumulative


def rebase_twr_series(twr_values) -> List[float]:
    """Rebase a TWR series to start from 0% at the first value.
    
    This is useful when you have a pre-calculated cumulative TWR series
    but want to show performance relative to a specific starting point
    (e.g., when filtering to show only last 1 year).
    
    Args:
        twr_values: List or Series of cumulative TWR percentages
        
    Returns:
        List of rebased TWR percentages starting at 0%
    """
    # Convert pandas Series to list if needed
    if hasattr(twr_values, 'tolist'):
        twr_values = twr_values.tolist()
    
    if not twr_values or len(twr_values) == 0:
        return []
    
    start_twr = twr_values[0]
    start_factor = 1 + start_twr / 100
    
    if start_factor <= 0:
        # Edge case: starting value implies -100% or worse
        return list(twr_values)
    
    # Rebase: convert from cumulative to relative from start of range
    # If start was at 50% cumulative, and current is 60%, relative is ~6.67%
    # Formula: ((1 + curr/100) / (1 + start/100) - 1) * 100
    return [((1 + t / 100) / start_factor - 1) * 100 for t in twr_values]


def calculate_drawdown_series(values: List[float]) -> List[float]:
    """Calculate drawdown series from peak.
    
    Drawdown = (current - peak) / peak * 100
    
    Args:
        values: List of portfolio values
        
    Returns:
        List of drawdown percentages (always <= 0)
    """
    if not values:
        return []
    
    values = np.array(values, dtype=float)
    
    # Calculate running maximum
    running_max = np.maximum.accumulate(values)
    running_max = np.where(running_max == 0, np.nan, running_max)
    
    # Calculate drawdown as percentage
    drawdown = (values - running_max) / running_max * 100
    drawdown = np.nan_to_num(drawdown, nan=0.0)
    
    return drawdown.tolist()


def calculate_performance_metrics(
    values: List[float],
    invested: List[float],
) -> Dict[str, float]:
    """Calculate key performance metrics for a portfolio.
    
    Args:
        values: List of portfolio values
        invested: List of invested amounts
        
    Returns:
        Dict with metrics: total_return, annualized_return, max_drawdown, volatility
    """
    if len(values) < 2:
        return {
            'total_return': 0.0,
            'annualized_return': 0.0,
            'max_drawdown': 0.0,
            'volatility': 0.0,
        }
    
    values = np.array(values, dtype=float)
    invested = np.array(invested, dtype=float)
    
    # TWR for accurate return calculation
    twr = calculate_twr_series(values.tolist(), invested.tolist())
    final_twr = twr[-1] if twr else 0.0
    
    # Max drawdown
    drawdown = calculate_drawdown_series(values.tolist())
    max_drawdown = min(drawdown) if drawdown else 0.0
    
    # Daily returns for volatility
    daily_returns = np.diff(values) / values[:-1]
    daily_returns = daily_returns[np.isfinite(daily_returns)]
    volatility = np.std(daily_returns) * np.sqrt(252) * 100 if len(daily_returns) > 1 else 0.0
    
    # Annualized return (assumes 252 trading days per year)
    n_days = len(values) - 1
    if n_days > 0 and final_twr > -100:
        annualized_return = ((1 + final_twr / 100) ** (252 / n_days) - 1) * 100
    else:
        annualized_return = 0.0
    
    return {
        'total_return': final_twr,
        'annualized_return': annualized_return,
        'max_drawdown': max_drawdown,
        'volatility': volatility,
    }


def build_cached_series(history: List[Dict]) -> Dict[str, List]:
    """Build pre-calculated series for caching.
    
    This function is called during TR sync to pre-calculate
    all the series needed for chart rendering.
    
    Args:
        history: List of {date, value, invested} dicts
        
    Returns:
        Dict with dates, values, invested, twr, drawdown lists
    """
    if not history or len(history) < 2:
        return {}
    
    # Sort by date
    sorted_history = sorted(history, key=lambda x: x.get('date', ''))
    
    df = pd.DataFrame(sorted_history)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    
    # Fill gaps with daily frequency
    df = df.set_index('date')
    full_date_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')
    df = df.reindex(full_date_range).ffill().reset_index().rename(columns={'index': 'date'})
    
    values = df['value'].tolist()
    invested = df['invested'].tolist() if 'invested' in df.columns else values
    
    # Calculate series
    twr = calculate_twr_series(values, invested)
    drawdown = calculate_drawdown_series(values)
    
    return {
        'dates': df['date'].dt.strftime('%Y-%m-%d').tolist(),
        'values': [float(v) if pd.notna(v) else None for v in values],
        'invested': [float(v) if pd.notna(v) else None for v in invested],
        'twr': [float(v) if v is not None else 0.0 for v in twr],
        'drawdown': [float(v) if v is not None else 0.0 for v in drawdown],
    }
