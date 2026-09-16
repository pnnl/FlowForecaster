"""
Scaling Pattern Detection Utilities

Classifies how an edge metric responds to a change of scale.

The response is fitted as a power law, y = c * k^p, against the scale
coordinate k that each instance was actually measured at.  The exponent p is
what the analytical rules are stated in terms of:

    p ~  0   metric is unchanged            (Rules 4, 6, and 7 under task scaling)
    p ~  1   metric is proportional to k    (Rules 1, 5, and 7 under data scaling)
    p ~ -1   metric is inversely proportional to k   (Rules 3 and 6)
    other    non-proportional; p is the constant the rule needs (Rule 2)

Fitting against the real scale coordinates rather than the position in the
argument list matters: a 2x/4x/8x series -- the one the paper evaluates -- looks
like a geometric sequence when indexed positionally, and the older
position-based cascade classified all of it as "exponential", which no
analytical rule matches, sending every edge to the empirical fallback.
"""

import numpy as np
from typing import List, Tuple, Dict, Any

# Response labels.
CONSTANT = "constant"
PROPORTIONAL = "proportional"
INVERSE = "inverse"
POWER = "power"
IRREGULAR = "irregular"
UNDETERMINED = "undetermined"

# Default matching threshold.  Sec. IV of the paper reports p "typically 10%".
DEFAULT_TOLERANCE = 0.10


def fit_power_law(scales: List[float], values: List[float]) -> Dict[str, Any]:
    """
    Least-squares fit of y = c * k^p, performed on log(y) against log(k).

    Returns the exponent, the coefficient, the worst relative residual, and the
    value predicted at k = 1.  Series containing a non-positive value cannot be
    fitted in log space; those are reported with fitted=False so the caller can
    fall back to the empirical rule instead of silently producing an exponent.
    """
    scales = [float(s) for s in scales]
    values = [float(v) for v in values]

    if len(scales) != len(values) or len(scales) < 2:
        return {"fitted": False, "reason": "need at least two measurements"}
    if len(set(scales)) < 2:
        return {"fitted": False, "reason": f"only one distinct scale in {sorted(set(scales))}"}
    if any(s <= 0 for s in scales):
        return {"fitted": False, "reason": "non-positive scale coordinate"}

    if all(v == values[0] for v in values):
        # Exactly constant: log-log would work but this is cheaper and exact.
        return {"fitted": True, "exponent": 0.0, "coefficient": values[0],
                "max_rel_err": 0.0, "at_unit_scale": values[0]}

    if any(v <= 0 for v in values):
        return {"fitted": False, "reason": "non-positive metric value"}

    log_k = np.log(scales)
    log_y = np.log(values)
    exponent, log_c = np.polyfit(log_k, log_y, 1)
    coefficient = float(np.exp(log_c))
    exponent = float(exponent)

    predicted = [coefficient * (s ** exponent) for s in scales]
    max_rel_err = max(abs(p - v) / v for p, v in zip(predicted, values))

    return {"fitted": True, "exponent": exponent, "coefficient": coefficient,
            "max_rel_err": float(max_rel_err), "at_unit_scale": coefficient}


def classify_response(scales: List[float], values: List[float],
                      tolerance: float = DEFAULT_TOLERANCE) -> Tuple[str, Dict[str, Any]]:
    """
    Label how `values` respond to `scales`, within a relative threshold.

    A series is only given an analytical label when the power law reproduces
    every measurement to within `tolerance`; otherwise it is IRREGULAR and the
    caller should fall back on the empirical rule rather than extrapolate a fit
    that does not describe its own training data.
    """
    fit = fit_power_law(scales, values)
    if not fit.get("fitted"):
        return UNDETERMINED, fit

    exponent = fit["exponent"]
    if fit["max_rel_err"] > tolerance:
        return IRREGULAR, fit

    if abs(exponent) <= tolerance:
        return CONSTANT, {**fit, "value": float(np.mean(values))}
    if abs(exponent - 1.0) <= tolerance:
        return PROPORTIONAL, fit
    if abs(exponent + 1.0) <= tolerance:
        return INVERSE, fit
    return POWER, fit


# ---------------------------------------------------------------------------
# Legacy, position-based API.
#
# Kept so existing callers keep working.  detect_scaling_pattern() now
# delegates to the scale-aware classifier: the old version tested
# check_linear_increase() first, and because check_linear_increase([1,1,1])
# succeeds with step 0, every constant series was labelled "linear_increase"
# and never reached check_constant().  Prefer classify_response() in new code.
# ---------------------------------------------------------------------------

_LEGACY_NAME = {
    CONSTANT: "constant",
    PROPORTIONAL: "linear_increase",
    INVERSE: "inverse",
    POWER: "polynomial",
    IRREGULAR: "unknown",
    UNDETERMINED: "unknown",
}


def compute_scaling_factors(values: List[float]) -> Tuple[List[float], bool]:
    """Values relative to the first value.  Factors are not scale coordinates."""
    if len(values) < 2:
        return [1.0], True
    base_value = values[0]
    if not base_value:
        return [1.0 for _ in values], True
    return [value / base_value for value in values], True


def detect_scaling_pattern(factors: List[float], tolerance: float = DEFAULT_TOLERANCE,
                           scales: List[float] = None) -> Tuple[str, Dict[str, Any]]:
    """
    Classify a series, returning a legacy pattern name.

    `scales` should be the coordinates the values were measured at.  Without
    them the series is assumed to be 1x, 2x, 3x, ..., which is the assumption
    that made non-uniform series unmatchable.
    """
    if len(factors) < 2:
        return "constant", {"value": factors[0] if factors else 0}
    if scales is None:
        scales = [float(i + 1) for i in range(len(factors))]
    label, params = classify_response(scales, factors, tolerance)
    if label == CONSTANT:
        return "constant", params
    if label == PROPORTIONAL and params.get("exponent", 1.0) < 0:
        return "linear_decrease", params
    return _LEGACY_NAME.get(label, "unknown"), params


def check_constant(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check whether every factor is the same, within tolerance of the mean."""
    if len(factors) < 2:
        return True, {"value": factors[0] if factors else 0}
    mean_factor = float(np.mean(factors))
    std_factor = float(np.std(factors))
    if not mean_factor or std_factor > abs(mean_factor) * tolerance:
        return False, {}
    return True, {"value": mean_factor, "std": std_factor}


def check_linear_increase(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check for a genuinely increasing arithmetic series (1, 2, 3, ...)."""
    if len(factors) < 2:
        return False, {}
    if check_constant(factors, tolerance)[0]:
        return False, {}  # a flat series is constant, not increasing
    differences = [factors[i + 1] - factors[i] for i in range(len(factors) - 1)]
    mean_diff = float(np.mean(differences))
    if mean_diff <= 0:
        return False, {}
    for diff in differences:
        if abs(diff - mean_diff) > abs(mean_diff) * tolerance:
            return False, {}
    return True, {"step": mean_diff, "base": factors[0]}


def check_linear_decrease(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check for a decreasing series, flagging the inverse case specially."""
    if len(factors) < 2:
        return False, {}
    for i in range(len(factors) - 1):
        if factors[i + 1] >= factors[i]:
            return False, {}
    if check_inverse(factors, tolerance)[0]:
        return True, {"type": "inverse", "base": factors[0]}
    differences = [factors[i + 1] - factors[i] for i in range(len(factors) - 1)]
    mean_diff = float(np.mean(differences))
    for diff in differences:
        if abs(diff - mean_diff) > abs(mean_diff) * tolerance:
            return False, {}
    return True, {"step": mean_diff, "base": factors[0]}


def check_inverse(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check factors[i] ~ base / (i + 1)."""
    if len(factors) < 2:
        return False, {}
    base = factors[0]
    for i, actual in enumerate(factors):
        expected = base / (i + 1)
        if not expected or abs(actual - expected) > abs(expected) * tolerance:
            return False, {}
    return True, {"base": base, "type": "inverse"}


def check_polynomial(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check for a power-law series with an integer exponent of 2 or 3."""
    if len(factors) < 3:
        return False, {}
    scales = [float(i + 1) for i in range(len(factors))]
    fit = fit_power_law(scales, factors)
    if not fit.get("fitted") or fit["max_rel_err"] > tolerance:
        return False, {}
    for degree in (2, 3):
        if abs(fit["exponent"] - degree) <= tolerance:
            return True, {"degree": degree, "coefficient": fit["coefficient"]}
    return False, {}


def check_exponential(factors: List[float], tolerance: float) -> Tuple[bool, Dict[str, Any]]:
    """Check for a geometric series (1, 2, 4, 8, ...) in argument order."""
    if len(factors) < 3 or any(f <= 0 for f in factors):
        return False, {}
    log_factors = np.log(factors)
    differences = [log_factors[i + 1] - log_factors[i] for i in range(len(log_factors) - 1)]
    mean_diff = float(np.mean(differences))
    if not mean_diff:
        return False, {}
    for diff in differences:
        if abs(diff - mean_diff) > abs(mean_diff) * tolerance:
            return False, {}
    base = float(np.exp(mean_diff))
    expected = [factors[0] * (base ** i) for i in range(len(factors))]
    for actual, exp in zip(factors, expected):
        if abs(actual - exp) > abs(exp) * tolerance:
            return False, {}
    return True, {"base": base, "initial": factors[0]}


def analyze_edge_scaling(values_dict: Dict[str, List[float]],
                         tolerance: float = DEFAULT_TOLERANCE,
                         scales: List[float] = None) -> Dict[str, Any]:
    """
    Classify every metric of one edge against the scales it was measured at.

    Returns, per metric, the fitted response label and parameters, the factors
    relative to the base measurement, and the raw values.
    """
    results = {}
    for metric_name, values in values_dict.items():
        if not values or len(values) < 2:
            results[f"{metric_name}_pattern"] = (CONSTANT, {"value": values[0] if values else 0})
            results[f"{metric_name}_factors"] = [1.0]
            results[f"{metric_name}_values"] = list(values or [])
            results[f"{metric_name}_fit"] = {"fitted": False, "reason": "single measurement"}
            continue
        coords = scales if scales is not None else [float(i + 1) for i in range(len(values))]
        label, params = classify_response(coords, values, tolerance)
        factors, _ = compute_scaling_factors(values)
        results[f"{metric_name}_factors"] = factors
        results[f"{metric_name}_pattern"] = (label, params)
        results[f"{metric_name}_values"] = list(values)
        results[f"{metric_name}_fit"] = params
    return results


def compare_patterns(pattern1: Tuple[str, Dict], pattern2: Tuple[str, Dict]) -> bool:
    """Whether two classified responses agree."""
    name1, params1 = pattern1
    name2, params2 = pattern2
    if name1 != name2:
        return False
    if name1 == CONSTANT:
        val1 = params1.get("value", 0)
        val2 = params2.get("value", 0)
        if val1:
            return abs(val1 - val2) / abs(val1) < DEFAULT_TOLERANCE
    return True


def infer_overall_scaling_type(edge_patterns: Dict[str, Any]) -> str:
    """Guess whether an edge's measurements came from a data- or task-scaling series."""
    volume_pattern, _ = edge_patterns.get("volume_pattern", (UNDETERMINED, {}))
    access_pattern, _ = edge_patterns.get("access_size_pattern", (UNDETERMINED, {}))
    if volume_pattern == PROPORTIONAL and access_pattern in (CONSTANT, PROPORTIONAL):
        return "data"
    if volume_pattern in (INVERSE, CONSTANT):
        return "task"
    return "unknown"
