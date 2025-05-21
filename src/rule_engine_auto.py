"""
Enhanced Rule Engine for FlowForecaster with Automatic Scaling Detection
Implements analytical scaling rules from the paper with pattern-based matching
"""

from abc import ABC, abstractmethod
import numpy as np
import sys
sys.path.append("../utils")
from py_lib_flowforecaster import EdgeType, VertexType
from py_lib_flowforecaster import EdgeAttrType, VertexAttrType


class ScalingRule(ABC):
    """Abstract base class for all scaling rules"""
    
    def __init__(self, rule_id: int, name: str):
        self.rule_id = rule_id
        self.name = name
    
    @abstractmethod
    def matches(self, edge_data: dict, pattern: str) -> bool:
        """Check if this rule matches the observed data pattern"""
        pass
    
    @abstractmethod
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        """Predict metrics at new scale"""
        pass
    
    def __str__(self):
        return f"Rule{self.rule_id}: {self.name}"


class Rule1(ScalingRule):
    """
    Fan-out: Varied input data size to fixed consumers
    When data size increases by k: A' = kA, V' = kV, S' = S
    """
    
    def __init__(self):
        super().__init__(1, "Proportional data scaling")
    
    def matches(self, edge_data: dict, pattern: str) -> bool:
        if pattern != EdgeType.FAN_OUT:
            return False
        
        # Check if this is data scaling
        if edge_data.get("scaling_type") != "data":
            return False
        
        volumes = edge_data.get("data_volumes", [])
        access_sizes = edge_data.get("access_sizes", [])
        
        if len(volumes) < 2:
            return False
        
        # Check patterns
        volume_pattern, _ = edge_data.get("volume_pattern", ("unknown", {}))
        access_pattern, _ = edge_data.get("access_size_pattern", ("unknown", {}))
        
        # Rule 1: Volume increases linearly, access size constant
        return (volume_pattern == "linear_increase" and 
                access_pattern == "constant")
    
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = scale_factor.get("data_scale", 1.0)
        return {
            EdgeAttrType.DATA_VOL: base_metrics[EdgeAttrType.DATA_VOL] * k,
            EdgeAttrType.ACC_SIZE: base_metrics[EdgeAttrType.ACC_SIZE],  # Unchanged
            "accesses": base_metrics.get("accesses", 1) * k
        }


class Rule2(ScalingRule):
    """
    Fan-out: Varied input data size with non-proportional scaling
    When data size increases by k: S' = k1*S, A' = k2*A, V' = k3*V
    """
    
    def __init__(self):
        super().__init__(2, "Non-proportional data scaling")
    
    def matches(self, edge_data: dict, pattern: str) -> bool:
        if pattern != EdgeType.FAN_OUT:
            return False
        
        if edge_data.get("scaling_type") != "data":
            return False
        
        volumes = edge_data.get("data_volumes", [])
        if len(volumes) < 2:
            return False
        
        # Check patterns
        volume_pattern, _ = edge_data.get("volume_pattern", ("unknown", {}))
        access_pattern, _ = edge_data.get("access_size_pattern", ("unknown", {}))
        
        # Rule 2: Some scaling but not proportional (catch-all for data scaling fan-out)
        return (volume_pattern == "linear_increase" and 
                access_pattern != "constant")
    
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = scale_factor.get("data_scale", 1.0)
        # Non-proportional scaling - use empirical factors
        return {
            EdgeAttrType.DATA_VOL: base_metrics[EdgeAttrType.DATA_VOL] * (k ** 1.2),
            EdgeAttrType.ACC_SIZE: base_metrics[EdgeAttrType.ACC_SIZE] * (k ** 0.8),
            "accesses": base_metrics.get("accesses", 1) * k
        }


class Rule3(ScalingRule):
    """
    Fan-out: Fixed input data size to varying consumers
    When consumers increase by k: V' = V/k, and either A' = A/k or S' = S/k
    """
    
    def __init__(self):
        super().__init__(3, "Fixed data, varied consumers")
    
    def matches(self, edge_data: dict, pattern: str) -> bool:
        if pattern != EdgeType.FAN_OUT:
            return False
        
        # Check if this is task scaling
        if edge_data.get("scaling_type") != "task":
            return False
        
        volumes = edge_data.get("data_volumes", [])
        if len(volumes) < 2:
            return False
        
        # Check patterns
        volume_pattern, _ = edge_data.get("volume_pattern", ("unknown", {}))
        
        # Rule 3: Volume decreases inversely with task count
        return volume_pattern in ["inverse", "linear_decrease"]
    
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = scale_factor.get("task_scale", 1.0)
        return {
            EdgeAttrType.DATA_VOL: base_metrics[EdgeAttrType.DATA_VOL] / k,
            EdgeAttrType.ACC_SIZE: base_metrics[EdgeAttrType.ACC_SIZE] / k,
            "accesses": base_metrics.get("accesses", 1)  # Unchanged
        }


class Rule4(ScalingRule):
    """
    Fan-out: Fixed input, varying consumers with constant transfer
    All metrics remain constant regardless of consumer count
    """
    
    def __init__(self):
        super().__init__(4, "Fixed data, constant transfer")
    
    def matches(self, edge_data: dict, pattern: str) -> bool:
        if pattern != EdgeType.FAN_OUT:
            return False
        
        if edge_data.get("scaling_type") != "task":
            return False
        
        volumes = edge_data.get("data_volumes", [])
        if len(volumes) < 2:
            return False
        
        # Check patterns
        volume_pattern, _ = edge_data.get("volume_pattern", ("unknown", {}))
        
        # Rule 4: Volume remains constant despite changing consumers
        return volume_pattern == "constant"
    
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        # All metrics remain constant
        return base_metrics.copy()


class Rule5(ScalingRule):
    """
    Fan-in: Consumer aggregates all inputs
    When inputs increase by k: V'Σ = k*VΣ, and either A'Σ = k*AΣ or S'Σ = k*SΣ
    """
    
    def __init__(self):
        super().__init__(5, "Fan-in aggregate")
    
    def matches(self, edge_data: dict, pattern: str) -> bool:
        if pattern != EdgeType.FAN_IN:
            return False
        
        if edge_data.get("scaling_type") != "task":
            return False
        
        volumes = edge_data.get("data_volumes", [])
        if len(volumes) < 2:
            return False
        
        # Check patterns
        volume_pattern, _ = edge_data.get("volume_pattern", ("unknown", {}))
        
        # Rule 5: Total volume increases with more sources
        return volume_pattern == "linear_increase"
    
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = scale_factor.get("task_scale", 1.0)
        return {
            EdgeAttrType.DATA_VOL: base_metrics[EdgeAttrType.DATA_VOL] * k,
            EdgeAttrType.ACC_SIZE: base_metrics[EdgeAttrType.ACC_SIZE],
            "accesses": base_metrics.get("accesses", 1) * k
        }


class Rule6(ScalingRule):
    """
    Fan-in: Consumer produces constant output
    Output volume unchanged, input volumes decrease with more sources
    """
    
    def __init__(self):
        super().__init__(6, "Fan-in constant output")
    
    def matches(self, edge_data: dict, pattern: str) -> bool:
        if pattern != EdgeType.FAN_IN:
            return False
        
        if edge_data.get("scaling_type") != "task":
            return False
        
        output_volumes = edge_data.get("output_volumes", [])
        if len(output_volumes) < 2:
            return False
        
        # Check patterns
        volume_pattern, _ = edge_data.get("volume_pattern", ("unknown", {}))
        
        # Rule 6: Output volume remains constant
        return volume_pattern == "constant"
    
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        k = scale_factor.get("task_scale", 1.0)
        return {
            EdgeAttrType.DATA_VOL: base_metrics[EdgeAttrType.DATA_VOL] / k,
            EdgeAttrType.ACC_SIZE: base_metrics[EdgeAttrType.ACC_SIZE] / k,
            "accesses": base_metrics.get("accesses", 1)  # Unchanged
        }


class Rule7(ScalingRule):
    """
    Sequential: Producer-consumer in sequence
    Task scaling: all metrics unchanged
    Data scaling: all metrics scale with data
    """
    
    def __init__(self):
        super().__init__(7, "Sequential")
    
    def matches(self, edge_data: dict, pattern: str) -> bool:
        if pattern != EdgeType.SEQ:
            return False
        
        volume_pattern, _ = edge_data.get("volume_pattern", ("unknown", {}))
        scaling_type = edge_data.get("scaling_type")
        
        if scaling_type == "data":
            # For data scaling, volumes should increase
            return volume_pattern == "linear_increase"
        elif scaling_type == "task":
            # For task scaling, volumes should remain constant
            return volume_pattern == "constant"
        
        return True  # Default match for sequential
    
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        if "data_scale" in scale_factor:
            k = scale_factor["data_scale"]
            return {
                EdgeAttrType.DATA_VOL: base_metrics[EdgeAttrType.DATA_VOL] * k,
                EdgeAttrType.ACC_SIZE: base_metrics[EdgeAttrType.ACC_SIZE] * k,
                "accesses": base_metrics.get("accesses", 1) * k
            }
        else:
            # Task scaling - no change
            return base_metrics.copy()


class Rule8(ScalingRule):
    """
    Empirical: Fallback for patterns not covered by analytical rules
    Uses observed data points for interpolation/extrapolation
    """
    
    def __init__(self):
        super().__init__(8, "Empirical fallback")
    
    def matches(self, edge_data: dict, pattern: str) -> bool:
        # Always matches as fallback
        return True
    
    def predict(self, scale_factor: dict, base_metrics: dict) -> dict:
        # Simple linear extrapolation as default
        k = scale_factor.get("data_scale", 1.0) * scale_factor.get("task_scale", 1.0)
        return {
            EdgeAttrType.DATA_VOL: base_metrics[EdgeAttrType.DATA_VOL] * k,
            EdgeAttrType.ACC_SIZE: base_metrics[EdgeAttrType.ACC_SIZE],
            "accesses": base_metrics.get("accesses", 1) * k
        }


def match_rule_based_on_patterns(stats, edge_pattern, scaling_type):
    """
    Match rules based on detected scaling patterns
    """
    volume_pattern, volume_params = stats["volume_pattern"]
    access_pattern, access_params = stats["access_size_pattern"]
    
    # Data scaling rules
    if scaling_type == "data":
        if edge_pattern == EdgeType.FAN_OUT:
            if volume_pattern == "linear_increase" and access_pattern == "constant":
                return Rule1()  # V' = kV, S' = S
            elif volume_pattern == "linear_increase":
                return Rule2()  # V' = k3V, S' = k1S, non-proportional
        elif edge_pattern == EdgeType.SEQ:
            if volume_pattern == "linear_increase":
                return Rule7()  # Sequential with data scaling
    
    # Task scaling rules
    elif scaling_type == "task":
        if edge_pattern == EdgeType.FAN_OUT:
            if volume_pattern == "inverse" or volume_pattern == "linear_decrease":
                return Rule3()  # V' = V/k
            elif volume_pattern == "constant":
                return Rule4()  # V' = V (constant)
        elif edge_pattern == EdgeType.FAN_IN:
            if volume_pattern == "linear_increase":
                return Rule5()  # V'Σ = k*VΣ
            elif volume_pattern == "constant":
                return Rule6()  # V'Σ = VΣ
        elif edge_pattern == EdgeType.SEQ:
            if volume_pattern == "constant":
                return Rule7()  # Sequential with task scaling
    
    # Default to empirical rule
    return Rule8()


class DeferredRule:
    """Wrapper for rules that need deferred evaluation"""
    
    def __init__(self, base_rule: ScalingRule, dependency: str):
        self.base_rule = base_rule
        self.dependency = dependency  # Task that must complete first
        self.is_resolved = False
        self.resolved_value = None
    
    def resolve(self, dependency_result):
        """Resolve the deferred rule with actual runtime data"""
        self.resolved_value = self.base_rule.predict(
            scale_factor=dependency_result["scale_factor"],
            base_metrics=dependency_result["base_metrics"]
        )
        self.is_resolved = True