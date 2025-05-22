"""
Scaling Pattern Detection Utilities
Automatically detects scaling patterns from observed data
"""

import numpy as np
from typing import List, Tuple, Dict, Any


def compute_scaling_factors(values: List[float]) -> Tuple[List[float], bool]:
    """
    Compute scaling factors relative to the first value
    Returns list of factors and whether they're consistent
    """
    if len(values) < 2:
        return [1.0], True
    
    base_value = values[0]
    factors = []
    
    for value in values:
        if base_value > 0:
            factors.append(value / base_value)
        else:
            factors.append(1.0)
    
    # Check if factors follow a pattern (e.g., 1, 2, 3 or 1, 0.5, 0.33)
    # Allow some tolerance for matching
    return factors, True


def detect_scaling_pattern(factors: List[float], tolerance: float = 0.15) -> Tuple[str, Dict[str, Any]]:
    """
    Detect if scaling factors follow a pattern
    Returns the pattern type and parameters
    """
    patterns = {
        "linear_increase": check_linear_increase(factors, tolerance),
        "linear_decrease": check_linear_decrease(factors, tolerance),
        "constant": check_constant(factors, tolerance),
        "inverse": check_inverse(factors, tolerance),
        "polynomial": check_polynomial(factors, tolerance),
        "exponential": check_exponential(factors, tolerance)
    }
    
    for pattern_name, (is_match, params) in patterns.items():
        if is_match:
            return pattern_name, params
    
    return "unknown", {}


def check_linear_increase(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check if factors follow pattern like 1, 2, 3..."""
    if len(factors) < 2:
        return False, {}
    
    # Check if differences are approximately constant
    differences = [factors[i+1] - factors[i] for i in range(len(factors)-1)]
    mean_diff = np.mean(differences)
    
    for diff in differences:
        if abs(diff - mean_diff) > abs(mean_diff) * tolerance:
            return False, {}
    
    # Additional check: factors should be approximately 1, 2, 3...
    expected = [1 + i * mean_diff for i in range(len(factors))]
    
    for actual, exp in zip(factors, expected):
        if abs(actual - exp) > exp * tolerance:
            return False, {}
    
    return True, {"step": mean_diff, "base": factors[0]}


def check_linear_decrease(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check if factors follow decreasing pattern"""
    if len(factors) < 2:
        return False, {}
    
    # Check if factors are monotonically decreasing
    for i in range(len(factors) - 1):
        if factors[i+1] >= factors[i]:
            return False, {}
    
    # Check if it's specifically inverse (1, 0.5, 0.33...)
    inverse_factors = [1.0 / (i + 1) for i in range(len(factors))]
    is_inverse = True
    
    for actual, expected in zip(factors, inverse_factors):
        if abs(actual - expected) > expected * tolerance:
            is_inverse = False
            break
    
    if is_inverse:
        return True, {"type": "inverse", "base": factors[0]}
    
    # Otherwise, check for linear decrease
    differences = [factors[i+1] - factors[i] for i in range(len(factors)-1)]
    mean_diff = np.mean(differences)
    
    for diff in differences:
        if abs(diff - mean_diff) > abs(mean_diff) * tolerance:
            return False, {}
    
    return True, {"step": mean_diff, "base": factors[0]}


def check_constant(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check if all factors are approximately the same"""
    if len(factors) < 2:
        return True, {"value": factors[0]}
    
    mean_factor = np.mean(factors)
    std_factor = np.std(factors)
    
    # Check if standard deviation is within tolerance of mean
    if std_factor > mean_factor * tolerance:
        return False, {}
    
    return True, {"value": mean_factor, "std": std_factor}


def check_inverse(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check if factors follow inverse relationship (1, 0.5, 0.33...)"""
    if len(factors) < 2:
        return False, {}
    
    # Check if factors[i] ≈ base/i
    base = factors[0]
    
    for i in range(len(factors)):
        expected = base / (i + 1)
        if abs(factors[i] - expected) > expected * tolerance:
            return False, {}
    
    return True, {"base": base, "type": "inverse"}


def check_polynomial(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check if factors follow polynomial pattern (1, 4, 9, 16...)"""
    if len(factors) < 3:
        return False, {}
    
    # Try to fit polynomial of degree 2
    x = np.arange(len(factors))
    
    # Quadratic check (x^2 pattern)
    expected_quadratic = [(i + 1) ** 2 / factors[0] for i in range(len(factors))]
    
    is_quadratic = True
    for actual, expected in zip(factors, expected_quadratic):
        if abs(actual - expected) > expected * tolerance:
            is_quadratic = False
            break
    
    if is_quadratic:
        return True, {"degree": 2, "coefficient": factors[0]}
    
    # Cubic check (x^3 pattern)
    expected_cubic = [(i + 1) ** 3 / factors[0] for i in range(len(factors))]
    
    is_cubic = True
    for actual, expected in zip(factors, expected_cubic):
        if abs(actual - expected) > expected * tolerance:
            is_cubic = False
            break
    
    if is_cubic:
        return True, {"degree": 3, "coefficient": factors[0]}
    
    return False, {}


def check_exponential(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check if factors follow exponential pattern (1, 2, 4, 8...)"""
    if len(factors) < 3:
        return False, {}
    
    # Check if log of factors is linear
    log_factors = np.log(factors)
    differences = [log_factors[i+1] - log_factors[i] for i in range(len(log_factors)-1)]
    mean_diff = np.mean(differences)
    
    for diff in differences:
        if abs(diff - mean_diff) > abs(mean_diff) * tolerance:
            return False, {}
    
    # Calculate base
    base = np.exp(mean_diff)
    
    # Verify
    expected = [factors[0] * (base ** i) for i in range(len(factors))]
    
    for actual, exp in zip(factors, expected):
        if abs(actual - exp) > exp * tolerance:
            return False, {}
    
    return True, {"base": base, "initial": factors[0]}


def analyze_edge_scaling(values_dict: Dict[str, List[float]], tolerance: float = 0.15) -> Dict[str, Any]:
    """
    Analyze scaling patterns for different metrics of an edge
    
    Args:
        values_dict: Dictionary with keys like 'volumes', 'access_sizes', etc.
        tolerance: Tolerance for pattern matching
    
    Returns:
        Dictionary with detected patterns and scaling factors
    """
    results = {}
    
    for metric_name, values in values_dict.items():
        if not values or len(values) < 2:
            results[f"{metric_name}_pattern"] = ("constant", {"value": values[0] if values else 0})
            results[f"{metric_name}_factors"] = [1.0]
            continue
        
        # Compute scaling factors
        factors, _ = compute_scaling_factors(values)
        
        # Detect pattern
        pattern, params = detect_scaling_pattern(factors, tolerance)
        
        results[f"{metric_name}_factors"] = factors
        results[f"{metric_name}_pattern"] = (pattern, params)
        results[f"{metric_name}_values"] = values
    
    return results


def compare_patterns(pattern1: Tuple[str, Dict], pattern2: Tuple[str, Dict]) -> bool:
    """
    Compare if two patterns are similar
    """
    name1, params1 = pattern1
    name2, params2 = pattern2
    
    if name1 != name2:
        return False
    
    # For constant patterns, check if values are close
    if name1 == "constant":
        val1 = params1.get("value", 0)
        val2 = params2.get("value", 0)
        if val1 > 0:
            return abs(val1 - val2) / val1 < 0.1
    
    return True


def infer_overall_scaling_type(edge_patterns: Dict[str, Any]) -> str:
    """
    Infer whether the edge represents data scaling or task scaling
    based on detected patterns
    """
    volume_pattern, _ = edge_patterns.get("volume_pattern", ("unknown", {}))
    access_pattern, _ = edge_patterns.get("access_size_pattern", ("unknown", {}))
    
    # Data scaling indicators
    if volume_pattern == "linear_increase" and access_pattern in ["constant", "linear_increase"]:
        return "data"
    
    # Task scaling indicators
    if volume_pattern in ["inverse", "linear_decrease", "constant"]:
        return "task"
    
    return "unknown"