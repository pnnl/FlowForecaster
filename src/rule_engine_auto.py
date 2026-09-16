"""
Rule Engine for FlowForecaster with Automatic Scaling Detection

Implements the eight analytical scaling rules of Sec. III of the paper.  Each
rule states how the properties of a data edge respond when the workflow is
scaled by a factor k, and each carries constants that are *fitted per edge from
the observed instances* rather than assumed.

Metric conventions
------------------
Traced instances record two quantities per edge: data volume V and access size
S.  Accesses A is recovered as A = V / S.

Sec. III-A calls accesses and access size the base metrics and volume derived,
but the rules as printed are not all consistent with V = A * S -- Rule 7 under
data scaling states A' = kA, S' = kS and V' = kV simultaneously, which would
require V' = k^2 V.  Prediction therefore follows the two measured quantities,
V and S, and reports A = V / S as derived.  Where a rule over-determines the
triple, `check_metric_consistency` reports it instead of hiding it.

Scale conventions
-----------------
Every rule is fitted at a reference scale (the smallest scale observed) and
predicts at a target scale.  The multiplier applied is k = target / reference,
so a model trained on 2x/4x/8x instances and asked for 4x predicts the same
absolute scale as a model trained on 1x/2x/3x and asked for 4x.
"""

from abc import ABC, abstractmethod
import math
import os
import sys

import numpy as np

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "utils"))
from py_lib_flowforecaster import EdgeType, VertexType
from py_lib_flowforecaster import EdgeAttrType, VertexAttrType

from scaling_pattern_detector import (
    CONSTANT, PROPORTIONAL, INVERSE, POWER, IRREGULAR, UNDETERMINED,
    DEFAULT_TOLERANCE, classify_response, fit_power_law,
)

VOL = EdgeAttrType.DATA_VOL
ACC = EdgeAttrType.ACC_SIZE
NUM_ACC = EdgeAttrType.ACCESSES
VOL_AGG = EdgeAttrType.VOL_AGGREGATE


def _exponent(series: dict, metric: str, tolerance: float) -> float:
    """Fitted exponent of one metric against the scale coordinates, or 0.0."""
    fit = fit_power_law(series.get("scales", []), series.get(metric, []))
    return fit["exponent"] if fit.get("fitted") else 0.0


def _reference(series: dict) -> float:
    scales = series.get("scales") or [1.0]
    return float(min(scales))


def _value_at_reference(series: dict, metric: str) -> float:
    """The measurement of `metric` taken at the reference scale."""
    scales = series.get("scales") or [1.0]
    values = series.get(metric) or [0.0]
    reference = _reference(series)
    for scale, value in zip(scales, values):
        if scale == reference:
            return float(value)
    return float(values[0])


def _ratio(scale_factor: dict, params: dict, keys=("data_scale", "task_scale")) -> float:
    """
    Target scale expressed relative to the scale the rule was fitted at.

    A rule fitted on 2x/4x/8x instances and asked to predict 4x applies a
    multiplier of 2, not 4.

    `keys` defaults to both dimensions on purpose.  Rules 1, 2, 3, 5 and 6 each
    used to pass a single key, so applying one to the other dimension found no
    key at all and quietly returned k = 1 -- a prediction of "nothing changes"
    that is indistinguishable from a rule that says so.  That mattered as soon as
    the matcher started selecting Rule 5 under data scaling, which is correct:
    Rule 5 constrains the aggregate, and a merge reading k times as much data has
    a proportional aggregate whichever dimension k came from.  A rule is a
    statement about a scale factor; which dimension produced it is the matcher's
    business.  Rule 7 is the exception and still branches explicitly, because its
    data and task cases make genuinely different statements.
    """
    target = None
    for key in keys:
        if key in scale_factor:
            target = float(scale_factor[key])
            break
    if target is None:
        target = 1.0
    reference = float((params or {}).get("reference_scale", 1.0)) or 1.0
    return target / reference


def _result(volume: float, access_size: float) -> dict:
    """Package a prediction, deriving accesses from the two measured metrics."""
    return {
        VOL: volume,
        ACC: access_size,
        NUM_ACC: (volume / access_size) if access_size else 0.0,
    }


def check_metric_consistency(series: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """
    Test the identity V = A * S against the observations.

    A is defined as V / S here, so the identity holds by construction; what this
    checks is whether the *fitted exponents* are consistent, i.e. whether
    p_V ~ p_A + p_S.  A violation means the three metrics do not scale as any
    single rule states and the edge is a candidate for Rule 8.
    """
    p_v = _exponent(series, "volume", tolerance)
    p_s = _exponent(series, "access_size", tolerance)
    p_a = _exponent(series, "accesses", tolerance)
    residual = abs(p_v - (p_a + p_s))
    return {"exponent_volume": p_v, "exponent_access_size": p_s,
            "exponent_accesses": p_a, "residual": residual,
            "consistent": residual <= max(tolerance, 1e-9)}


class ScalingRule(ABC):
    """Abstract base class for all scaling rules."""

    def __init__(self, rule_id: int, name: str, params: dict = None):
        self.rule_id = rule_id
        self.name = name
        self.params = dict(params or {})

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        """Predict metrics at new scale."""

    def fit(self, series: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
        """
        Derive this rule's constants from the observed series.

        The base class records only the reference scale; rules with free
        constants override this.
        """
        self.params.setdefault("reference_scale", _reference(series))
        return self.params

    def describe(self) -> str:
        """Human-readable form of the fitted rule, for the model and Table-I style output."""
        return str(self)

    def __str__(self):
        return f"Rule{self.rule_id}: {self.name}"


class Rule1(ScalingRule):
    """
    Fan-out: varied input data size to a fixed number of consumers.
    Increasing input data by k: A' = kA, V' = kV, S' = S.
    """

    def __init__(self, params: dict = None):
        super().__init__(1, "Proportional data scaling", params)

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = _ratio(scale_factor, self.params)
        return _result(base_metrics[VOL] * k, base_metrics[ACC])

    def describe(self) -> str:
        return "V' = kV, S' = S, A' = kA"


class Rule2(ScalingRule):
    """
    Fan-out: varied input data size, non-proportional response.
    S' = k1*S, A' = k2*A, V' = k3*V.

    k1, k2 and k3 are constants of the edge, not of the rule.  They are fitted
    as exponents of k so that one model serves every target scale:
    k1 = k^p_S, k2 = k^p_A, k3 = k^p_V.  The previous implementation hardcoded
    k^1.2 and k^0.8 for every edge in every workflow.
    """

    def __init__(self, params: dict = None):
        super().__init__(2, "Non-proportional data scaling", params)

    def fit(self, series: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
        self.params["reference_scale"] = _reference(series)
        self.params["exponent_volume"] = _exponent(series, "volume", tolerance)
        self.params["exponent_access_size"] = _exponent(series, "access_size", tolerance)
        self.params["exponent_accesses"] = _exponent(series, "accesses", tolerance)
        return self.params

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = _ratio(scale_factor, self.params)
        p_v = float(self.params.get("exponent_volume", 1.0))
        p_s = float(self.params.get("exponent_access_size", 0.0))
        return _result(base_metrics[VOL] * (k ** p_v), base_metrics[ACC] * (k ** p_s))

    def describe(self) -> str:
        return (f"V' = k^{self.params.get('exponent_volume', 1.0):.3f} V, "
                f"S' = k^{self.params.get('exponent_access_size', 0.0):.3f} S")


class Rule3(ScalingRule):
    """
    Fan-out: fixed input data size to a varying number of consumers.
    V' = V/k, and *either* A' = A/k or S' = S/k.

    Which of the two decreases is a property of the edge, so the branch is
    chosen from the observations rather than applying both (applying both
    divides volume by k^2 once volume is derived).
    """

    def __init__(self, params: dict = None):
        super().__init__(3, "Fixed data, varied consumers", params)

    def fit(self, series: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
        self.params["reference_scale"] = _reference(series)
        p_s = _exponent(series, "access_size", tolerance)
        # S' = S/k means p_S ~ -1; otherwise the decrease is in accesses.
        self.params["branch"] = "access_size" if abs(p_s + 1.0) <= max(tolerance, 0.5) else "accesses"
        self.params["exponent_access_size"] = p_s
        return self.params

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = _ratio(scale_factor, self.params)
        volume = base_metrics[VOL] / k if k else base_metrics[VOL]
        if self.params.get("branch") == "access_size":
            return _result(volume, base_metrics[ACC] / k if k else base_metrics[ACC])
        return _result(volume, base_metrics[ACC])

    def describe(self) -> str:
        branch = self.params.get("branch", "accesses")
        return f"V' = V/k, {'S' if branch == 'access_size' else 'A'}' = {'S' if branch == 'access_size' else 'A'}/k"


class Rule4(ScalingRule):
    """
    Fan-out: fixed input, varying consumers, constant transfer.
    A' = A, S' = S, V' = V along each data-consumer edge.
    """

    def __init__(self, params: dict = None):
        super().__init__(4, "Fixed data, constant transfer", params)

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        return _result(base_metrics[VOL], base_metrics[ACC])

    def describe(self) -> str:
        return "V' = V, S' = S, A' = A"


class Rule5(ScalingRule):
    """
    Fan-in: consumer aggregates all inputs.
    V_sigma' = k*V_sigma, and either A_sigma' = k*A_sigma or S_sigma' = k*S_sigma.

    The rule constrains the *aggregate* over the in-edge set (Eq. 1), so it is
    matched and predicted on the aggregate.  The per-edge volume that the
    projected DAG needs is then the aggregate divided by the in-degree at the
    target scale.
    """

    def __init__(self, params: dict = None):
        super().__init__(5, "Fan-in aggregate", params)

    def fit(self, series: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
        self.params["reference_scale"] = _reference(series)
        p_s = _exponent(series, "access_size", tolerance)
        self.params["branch"] = "access_size" if abs(p_s - 1.0) <= max(tolerance, 0.5) else "accesses"
        self.params["exponent_num_sources"] = _exponent(series, "num_sources", tolerance)
        self.params["aggregate_at_reference"] = _value_at_reference(series, "volume_aggregate")
        return self.params

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = _ratio(scale_factor, self.params)
        aggregate = base_metrics.get(VOL_AGG, base_metrics[VOL]) * k
        # In-degree grows with the number of producers being aggregated.
        p_src = float(self.params.get("exponent_num_sources", 1.0))
        in_degree = max(1.0, float(base_metrics.get(EdgeAttrType.NUM_SRC, 1.0)) * (k ** p_src))
        access_size = base_metrics[ACC] * k if self.params.get("branch") == "access_size" else base_metrics[ACC]
        prediction = _result(aggregate / in_degree, access_size)
        prediction[VOL_AGG] = aggregate
        prediction[EdgeAttrType.NUM_SRC] = in_degree
        return prediction

    def describe(self) -> str:
        branch = self.params.get("branch", "accesses")
        tag = "S_sigma" if branch == "access_size" else "A_sigma"
        return f"V_sigma' = k V_sigma, {tag}' = k {tag}"


class Rule6(ScalingRule):
    """
    Fan-in: consumer produces a constant-size output.
    V_sigma' = V_sigma, V' = V/k, S' = S/k' where k' = alpha*k, alpha constant.

    alpha is fitted per edge.  The previous implementation divided access size
    by k, i.e. assumed alpha = 1 for every edge.
    """

    def __init__(self, params: dict = None):
        super().__init__(6, "Fan-in constant output", params)

    def fit(self, series: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
        self.params["reference_scale"] = _reference(series)
        reference = _reference(series)

        # Like Rules 3 and 5, this rule offers two alternatives and the data
        # picks one: the shrinking per-producer share shows up either in the
        # access size, S' = S/(alpha k), or in the access count with S held
        # fixed.  Forcing the access-size branch unconditionally -- as this did --
        # is unfittable whenever S is genuinely constant: alpha comes out as 1/k,
        # a different value at every scale, and averaging those predicts neither.
        p_s = _exponent(series, "access_size", tolerance)
        self.params["branch"] = "access_size" if abs(p_s + 1.0) <= max(tolerance, 0.5) else "accesses"

        if self.params["branch"] == "access_size":
            # S(k) = S_ref / (alpha k)  =>  alpha = S_ref / (S(k) k).
            scales = series.get("scales") or [1.0]
            sizes = series.get("access_size") or [1.0]
            s_ref = _value_at_reference(series, "access_size")
            alphas = []
            for scale, size in zip(scales, sizes):
                k = float(scale) / reference
                if k > 1.0 and size:
                    alphas.append(s_ref / (size * k))
            self.params["alpha"] = float(np.mean(alphas)) if alphas else 1.0
        else:
            self.params["alpha"] = 1.0

        self.params["exponent_num_sources"] = _exponent(series, "num_sources", tolerance)
        self.params["aggregate_at_reference"] = _value_at_reference(series, "volume_aggregate")
        return self.params

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = _ratio(scale_factor, self.params)
        alpha = float(self.params.get("alpha", 1.0)) or 1.0
        aggregate = base_metrics.get(VOL_AGG, base_metrics[VOL])
        p_src = float(self.params.get("exponent_num_sources", 1.0))
        in_degree = max(1.0, float(base_metrics.get(EdgeAttrType.NUM_SRC, 1.0)) * (k ** p_src))
        if self.params.get("branch") == "access_size" and k:
            access_size = base_metrics[ACC] / (alpha * k)
        else:
            access_size = base_metrics[ACC]
        prediction = _result(aggregate / in_degree, access_size)
        prediction[VOL_AGG] = aggregate
        prediction[EdgeAttrType.NUM_SRC] = in_degree
        return prediction

    def describe(self) -> str:
        if self.params.get("branch") == "access_size":
            return f"V_sigma' = V_sigma, V' = V/k, S' = S/({self.params.get('alpha', 1.0):.3f}k)"
        return "V_sigma' = V_sigma, V' = V/k, A' = A/k, S' = S"


class Rule7(ScalingRule):
    """
    Sequential producer-consumer.
    Task scaling: A' = A, S' = S, V' = V.
    Data scaling: A' = kA, S' = kS, V' = kV.

    The paper states all three metrics scaling by k for data scaling, which
    over-determines the triple under V = A*S.  V and S are the measured
    quantities, so both are scaled as stated and A is reported as V'/S'.  When
    the observations disagree with that -- for example S constant while V scales
    -- the fitted exponents are recorded and used, so the model follows the
    workflow rather than the idealised statement.
    """

    def __init__(self, params: dict = None):
        super().__init__(7, "Sequential", params)

    def fit(self, series: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
        self.params["reference_scale"] = _reference(series)
        self.params["exponent_volume"] = _exponent(series, "volume", tolerance)
        self.params["exponent_access_size"] = _exponent(series, "access_size", tolerance)
        return self.params

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        if "data_scale" in scale_factor:
            k = _ratio(scale_factor, self.params, ("data_scale",))
            p_v = float(self.params.get("exponent_volume", 1.0))
            p_s = float(self.params.get("exponent_access_size", 1.0))
            return _result(base_metrics[VOL] * (k ** p_v), base_metrics[ACC] * (k ** p_s))
        return _result(base_metrics[VOL], base_metrics[ACC])

    def describe(self) -> str:
        if "exponent_volume" not in self.params:
            return "V' = V, S' = S, A' = A"
        return (f"V' = k^{self.params.get('exponent_volume', 0.0):.3f} V, "
                f"S' = k^{self.params.get('exponent_access_size', 0.0):.3f} S")


class Rule8(ScalingRule):
    """
    Empirical fallback for edges no analytical rule covers.

    Sec. III says to "record all vertex and edge properties to seed a
    data-dependent model".  This keeps the measured (scale, value) table and
    interpolates within it, extrapolating with a power law fitted to the same
    table.  It does not invent a relationship: an edge whose measurements are
    flat stays flat, and one that was never observed to change is not scaled.
    """

    def __init__(self, params: dict = None):
        super().__init__(8, "Empirical fallback", params)

    def fit(self, series: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
        self.params["reference_scale"] = _reference(series)
        self.params["observations"] = {
            "scales": [float(s) for s in series.get("scales", [])],
            "volume": [float(v) for v in series.get("volume", [])],
            "access_size": [float(v) for v in series.get("access_size", [])],
            "volume_aggregate": [float(v) for v in series.get("volume_aggregate", [])],
        }
        self.params["exponent_volume"] = _exponent(series, "volume", tolerance)
        self.params["exponent_access_size"] = _exponent(series, "access_size", tolerance)
        # The aggregate needs its own exponent.  Without one _empirical() read a
        # missing key as 0.0 and extrapolated the aggregate flat past the measured
        # range, so an edge whose volume was observed falling as 1/k had its
        # aggregate predicted constant -- disagreeing with its own volume.
        self.params["exponent_volume_aggregate"] = _exponent(series, "volume_aggregate", tolerance)
        return self.params

    def _empirical(self, metric: str, target: float, fallback: float) -> float:
        table = (self.params.get("observations") or {})
        scales = table.get("scales") or []
        values = table.get(metric) or []
        if len(scales) != len(values) or not scales:
            return fallback
        pairs = sorted(zip(scales, values))
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        if len(xs) == 1:
            return ys[0]
        if xs[0] <= target <= xs[-1]:
            # Interpolate in log-log space, the same space this rule extrapolates
            # in.  A straight line in linear space is the wrong curve for a
            # multiplicative series and disagreed with the rule's own fitted
            # exponent: on a clean 1/k series measured at 1x/4x/8x, the chord from
            # (1, V) to (4, V/4) puts 2x at 0.75V where the power law -- and the
            # measurement -- give 0.5V, a 50% error, and predictions jumped
            # discontinuously at the edge of the measured range where the two laws
            # met.  Log-log interpolation is exact for any true power law, is
            # continuous with the extrapolation branch, and still leaves a flat
            # series flat.  Non-positive values have no logarithm, so those fall
            # back to the linear chord.
            if xs[0] > 0 and all(y > 0 for y in ys):
                return float(math.exp(np.interp(math.log(target),
                                                [math.log(x) for x in xs],
                                                [math.log(y) for y in ys])))
            return float(np.interp(target, xs, ys))
        exponent = float(self.params.get(f"exponent_{metric}", 0.0))
        anchor_x, anchor_y = (xs[0], ys[0]) if target < xs[0] else (xs[-1], ys[-1])
        if anchor_x <= 0 or not anchor_y:
            return fallback
        return anchor_y * ((target / anchor_x) ** exponent)

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        target = None
        for key in ("data_scale", "task_scale"):
            if key in scale_factor:
                target = float(scale_factor[key])
                break
        if target is None:
            return _result(base_metrics[VOL], base_metrics[ACC])
        volume = self._empirical("volume", target, base_metrics[VOL])
        access_size = self._empirical("access_size", target, base_metrics[ACC])
        prediction = _result(volume, access_size)
        if VOL_AGG in base_metrics:
            prediction[VOL_AGG] = self._empirical("volume_aggregate", target, base_metrics[VOL_AGG])
        return prediction

    def describe(self) -> str:
        table = (self.params.get("observations") or {}).get("scales") or []
        return f"empirical, seeded from {len(table)} measured scale(s)"


class DeferredRule:
    """
    A rule whose inputs are only known at runtime (Sec. III-F).

    Sec. IV-A-4 describes SRA Search, whose first stage downloads files of
    unpredictable size; dataflow for later stages cannot be predicted until that
    stage runs.  Such an edge keeps its analytical rule but is marked so the
    caller evaluates it lazily, once the dependency has produced real sizes.

    `resolve` re-bases the rule on the measured metrics and then applies it.
    """

    def __init__(self, base_rule: ScalingRule, dependency: str, reason: str = ""):
        self.base_rule = base_rule
        self.dependency = dependency  # vertex whose runtime output the rule needs
        self.reason = reason
        self.is_resolved = False
        self.resolved_value = None

    @property
    def rule_id(self):
        return self.base_rule.rule_id

    @property
    def name(self):
        return f"{self.base_rule.name} (deferred on {self.dependency})"

    @property
    def params(self):
        return dict(self.base_rule.params, deferred_on=self.dependency, deferred_reason=self.reason)

    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        """Predict optimistically; callers should prefer resolve() once data exists."""
        return self.base_rule.predict(scale_factor, base_metrics)

    def resolve(self, dependency_result: dict) -> dict:
        """Evaluate the rule against metrics measured at runtime."""
        self.resolved_value = self.base_rule.predict(
            scale_factor=dependency_result["scale_factor"],
            base_metrics=dependency_result["base_metrics"],
        )
        self.is_resolved = True
        return self.resolved_value

    def describe(self) -> str:
        return f"{self.base_rule.describe()} [deferred until {self.dependency} completes]"

    def __str__(self):
        return f"Rule{self.base_rule.rule_id}*: {self.name}"


RULE_CLASSES = {1: Rule1, 2: Rule2, 3: Rule3, 4: Rule4, 5: Rule5, 6: Rule6, 7: Rule7, 8: Rule8}


def build_rule(rule_id, params: dict = None) -> ScalingRule:
    """Reconstruct a fitted rule from a stored id and parameter dict."""
    try:
        key = int(rule_id)
    except (TypeError, ValueError):
        digits = "".join(ch for ch in str(rule_id) if ch.isdigit())
        key = int(digits) if digits else 8
    return RULE_CLASSES.get(key, Rule8)(params or {})


def match_rule_based_on_patterns(stats, edge_pattern, scaling_type):
    """
    Choose the rule whose stated response matches the observed one.

    `stats` carries the classified responses of volume, access size and the
    fan-in aggregate (Eq. 1), plus the vertex context needed to tell Rule 5 from
    Rule 6: those two are distinguished by what happens to the *consumer's
    output*, which is not visible on the fan-in edge itself.
    """
    volume_pattern, _ = stats.get("volume_pattern", (UNDETERMINED, {}))
    access_pattern, _ = stats.get("access_size_pattern", (UNDETERMINED, {}))
    aggregate_pattern, _ = stats.get("volume_aggregate_pattern", (UNDETERMINED, {}))
    output_pattern, _ = stats.get("output_volume_pattern", (UNDETERMINED, {}))

    if scaling_type == "data":
        # An edge carrying a fixed amount of data regardless of the input size is
        # Rule 4's "fixed input data" case, whatever its fan pattern: the rule
        # states A' = A, S' = S, V' = V.  Tested first so a constant edge is
        # given its analytical form instead of falling through to Rule 8.
        if volume_pattern == CONSTANT and access_pattern == CONSTANT:
            if edge_pattern == EdgeType.FAN_IN and aggregate_pattern != CONSTANT:
                pass  # aggregate still moves; fall through to the fan-in rules
            else:
                return Rule4()

        if edge_pattern == EdgeType.FAN_OUT:
            if volume_pattern == PROPORTIONAL and access_pattern == CONSTANT:
                return Rule1()
            if volume_pattern in (PROPORTIONAL, POWER):
                return Rule2()
        elif edge_pattern == EdgeType.FAN_IN:
            # Rules 5 and 6 are separated by what happens to the *aggregate*:
            # Rule 5 states V_sigma' = k V_sigma, Rule 6 states V_sigma' =
            # V_sigma.  So the aggregate decides, and a constant output from the
            # consumer only breaks the tie when the aggregate cannot be fitted.
            #
            # Testing the output first, as this did, mis-assigns a merge that
            # reads k times as much data to write a fixed-size archive: its
            # output is constant, but Rule 6 would then predict a constant input
            # aggregate, which is the one thing the measurements rule out.
            if aggregate_pattern == PROPORTIONAL:
                return Rule5()
            if aggregate_pattern == CONSTANT:
                return Rule6()
            if output_pattern == CONSTANT and aggregate_pattern in (UNDETERMINED, IRREGULAR):
                return Rule6()
        elif edge_pattern == EdgeType.SEQ:
            if volume_pattern == PROPORTIONAL:
                return Rule7()

    elif scaling_type == "task":
        if edge_pattern == EdgeType.FAN_OUT:
            if volume_pattern == INVERSE:
                return Rule3()
            if volume_pattern == CONSTANT:
                return Rule4()
        elif edge_pattern == EdgeType.FAN_IN:
            if aggregate_pattern == PROPORTIONAL:
                return Rule5()
            if aggregate_pattern == CONSTANT:
                return Rule6()
        elif edge_pattern == EdgeType.SEQ:
            if volume_pattern == CONSTANT:
                return Rule7()

    return Rule8()


def deferral_candidate(stats, tolerance: float = DEFAULT_TOLERANCE) -> bool:
    """
    Whether an edge *looks* data-dependent rather than scale-dependent.

    The signal is the one Sec. III-F points at: the folded threads and
    iterations of a single instance disagree by more than the matching
    threshold, so part of the spread cannot be explained by scale.

    This is a report, not a decision.  Iteration-to-iteration variance is normal
    in real traces and is exactly what averaging over the folds handles, so
    treating this signal as sufficient grounds for deferral marks almost every
    edge of almost every workflow.  Whether a stage's inputs are genuinely
    unknown until a predecessor runs -- SRA Search's case, the stages the paper
    marks with '*' -- is a property of the workflow that a single trace cannot
    establish.  The caller decides, from --defer-on or --auto-defer.
    """
    return float(stats.get("max_within_instance_cv", 0.0)) > tolerance


# Older name; kept so existing callers keep working.
needs_deferral = deferral_candidate
