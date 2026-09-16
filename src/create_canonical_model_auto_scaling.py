"""
Build a canonical scaling model from a series of traced workflow instances.

Pipeline, following Sec. III of the paper:

  1. Space-time folding reduces each instance to its core graph.
  2. Every folded measurement on every core edge is reduced to one observation
     per instance, tagged with the scale that instance was traced at.
  3. Each metric's response across scales is fitted as a power law.
  4. The rule whose stated response matches is selected and its constants are
     fitted from the same observations.

Two things about step 2 are worth stating, because getting them wrong quietly
degrades everything downstream.  A folded edge attribute is a matrix indexed
[thread][iteration], so a 2-thread 3-iteration fold holds six measurements; all
six are used.  And the scale coordinate travels with the observation instead of
being inferred from argument position, so a 2x/4x/8x series is fitted as 2/4/8
rather than as 1/2/3.
"""

import argparse
import os
import sys
from collections import defaultdict

import numpy as np
import networkx as nx

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "utils"))
from py_lib_flowforecaster import EdgeType, VertexType
from py_lib_flowforecaster import EdgeAttrType, VertexAttrType
from py_lib_flowforecaster import write_graphml_encoded, read_graphml_decoded

from measurements import cells, observe_edge, resolve_scales, summarize
from rule_engine_auto import (
    match_rule_based_on_patterns,
    deferral_candidate,
    check_metric_consistency,
    DeferredRule,
    Rule8,
    VOL, ACC, NUM_ACC, VOL_AGG,
)
from scaling_pattern_detector import (
    analyze_edge_scaling,
    fit_power_law,
    infer_overall_scaling_type,
    DEFAULT_TOLERANCE,
    CONSTANT, UNDETERMINED,
)
from project_at_scale import project_core_graph, unfold

from do_space_time_folding import (
    divide_threads,
    construct_compound_graph,
    fold_thread_first_iteration,
    fold_thread_all_iterations,
)

# The metrics whose scale response is classified.  Volume and access size are
# measured; accesses is derived as V/S; the aggregate is Eq. 1; the two
# multiplicities drive structural projection.
METRICS = ("volume", "access_size", "accesses", "volume_aggregate",
           "num_sources", "num_destinations")


def fold_instance(instance_file: str) -> nx.DiGraph:
    """Reduce one traced instance to its core graph by space-time folding."""
    threads_list = divide_threads(filename=instance_file)

    compound_results = construct_compound_graph(G=threads_list[0])
    compound_graph = compound_results["compound_graph"]
    boundary_task_prefix_set = compound_results["boundary_task_prefix_set"]

    first_iteration_snapshots = [compound_results]
    for t_i in range(1, len(threads_list)):
        first_iteration_snapshots.append(fold_thread_first_iteration(
            compound_graph=compound_graph,
            G=threads_list[t_i],
            boundary_task_prefix_set=boundary_task_prefix_set))

    for thread_i, snapshot in enumerate(first_iteration_snapshots):
        fold_thread_all_iterations(workflow_thread_id=thread_i, **snapshot)

    compound_graph.graph["num_threads"] = len(threads_list)
    return compound_graph


def _new_edge_record():
    record = {"scales": [], "instances": [], "pattern": None,
              "max_within_instance_cv": 0.0, "folds": 0}
    for metric in METRICS:
        record[metric] = []
    return record


def observe_instances(instance_files: list, scaling_type: str, scales: list) -> tuple:
    """
    Fold every instance and reduce it to one observation per core edge.

    Returns (core_graphs, edge_series, vertex_series).  Each edge's series
    carries its own scale coordinates, so an edge that only exists in some of
    the instances is still fitted against the scales it was actually seen at.
    """
    core_graphs = []
    edge_series = defaultdict(_new_edge_record)
    vertex_series = defaultdict(lambda: {"scales": [], "size": [], "output_volume": [],
                                         "type": None})

    for instance_file, scale in zip(instance_files, scales):
        print(f"\nProcessing {instance_file} for {scaling_type} scaling (scale {scale}x)...")
        core_graph = fold_instance(instance_file)
        core_graphs.append(core_graph)
        print(f"  Core graph: {core_graph.number_of_nodes()} vertices, "
              f"{core_graph.number_of_edges()} edges, "
              f"{core_graph.graph.get('num_threads')} threads folded")

        measured_cells = 0
        for src, dst, edge_data in core_graph.edges(data=True):
            observation = observe_edge(core_graph, src, dst, edge_data, scale, instance_file)
            measured_cells += observation.folds

            record = edge_series[(src, dst)]
            record["scales"].append(observation.scale)
            record["instances"].append(instance_file)
            record["pattern"] = observation.edge_type
            record["volume"].append(observation.volume)
            record["access_size"].append(observation.access_size)
            record["accesses"].append(observation.accesses)
            record["volume_aggregate"].append(observation.volume_aggregate)
            record["num_sources"].append(observation.num_sources)
            record["num_destinations"].append(observation.num_destinations)
            record["folds"] = max(record["folds"], observation.folds)
            record["max_within_instance_cv"] = max(record["max_within_instance_cv"],
                                                   observation.max_cv)

        # Vertex context.  Rule 5 and Rule 6 differ in what happens to the
        # consumer's *output*, which is invisible on the fan-in edge itself.
        for vertex, attrs in core_graph.nodes(data=True):
            out_volume = 0.0
            for _, consumer, edge_data in core_graph.out_edges(vertex, data=True):
                observation = observe_edge(core_graph, vertex, consumer, edge_data, scale)
                out_volume += observation.volume * max(1.0, observation.num_destinations)

            size_cells = cells(attrs.get(VertexAttrType.SIZE))
            series = vertex_series[vertex]
            series["scales"].append(scale)
            series["size"].append(float(np.mean(size_cells)) if size_cells else 0.0)
            series["output_volume"].append(out_volume)
            series["type"] = attrs.get(VertexAttrType.TYPE)

        print(f"  Used {measured_cells} folded measurements "
              f"({core_graph.number_of_edges()} edges)")

    return core_graphs, edge_series, vertex_series


def classify_responses(edge_series: dict, vertex_series: dict, tolerance: float):
    """Fit each metric's response to scale, and attach the consumer's output response."""
    for (src, dst), record in edge_series.items():
        values = {metric: record[metric] for metric in METRICS}
        record.update(analyze_edge_scaling(values, tolerance, record["scales"]))

        consumer = vertex_series.get(dst, {})
        if consumer.get("output_volume"):
            label, params = _classify(consumer["scales"], consumer["output_volume"], tolerance)
            record["output_volume_pattern"] = (label, params)
        else:
            record["output_volume_pattern"] = (UNDETERMINED, {})

        record["consistency"] = check_metric_consistency(record, tolerance)


def _classify(scales, values, tolerance):
    from scaling_pattern_detector import classify_response
    return classify_response(scales, values, tolerance)


def infer_rules(edge_series: dict, scaling_type: str, tolerance: float,
                defer_on: set = frozenset(), auto_defer: bool = False) -> dict:
    """
    Select and fit one rule per core edge.

    Selection is by matching the observed response against each rule's stated
    response; the rule's own constants are then fitted from the same
    observations rather than assumed.

    `defer_on` names vertices whose output size is only known at runtime, so
    rules on their out-edges are evaluated lazily (Sec. III-F).  That is a
    property of the workflow, not something a trace reveals, so it is an input.
    `auto_defer` additionally defers every edge flagged as a candidate by its
    within-instance spread; it is off by default because in practice that flags
    nearly every edge.
    """
    edge_rules = {}
    candidates = []

    for (src, dst), record in edge_series.items():
        rule = match_rule_based_on_patterns(record, record["pattern"], scaling_type)
        rule.fit(record, tolerance)

        is_candidate = deferral_candidate(record, tolerance)
        if is_candidate:
            candidates.append((src, dst, record["max_within_instance_cv"]))
        if src in defer_on or (auto_defer and is_candidate):
            reason = (f"size of '{src}' is known only at runtime"
                      if src in defer_on else
                      f"within-instance spread {record['max_within_instance_cv']:.1%} "
                      f"exceeds the {tolerance:.0%} matching threshold")
            rule = DeferredRule(rule, dependency=src, reason=reason)

        edge_rules[(src, dst)] = {
            "rule": rule,
            "series": record,
            "confidence": rule_confidence(record, rule, tolerance),
        }

        volume_label, _ = record.get("volume_pattern", (UNDETERMINED, {}))
        access_label, _ = record.get("access_size_pattern", (UNDETERMINED, {}))
        aggregate_label, _ = record.get("volume_aggregate_pattern", (UNDETERMINED, {}))
        print(f"\n  ({src}) -> ({dst})  [{record['pattern']}]")
        print(f"    scales {record['scales']}")
        print(f"    V {_fmt(record['volume'])} -> {volume_label}")
        print(f"    S {_fmt(record['access_size'])} -> {access_label}")
        print(f"    V_sigma {_fmt(record['volume_aggregate'])} -> {aggregate_label}")
        marker = "  [deferral candidate]" if is_candidate and not isinstance(rule, DeferredRule) else ""
        print(f"    {rule}  (confidence {edge_rules[(src, dst)]['confidence']:.2f}){marker}")

    if candidates and not auto_defer and not defer_on:
        print(f"\n  {len(candidates)} of {len(edge_rules)} edges vary within a single instance "
              f"by more than {tolerance:.0%}.")
        print(f"  Their rules were still applied eagerly.  Pass --defer-on <task> for stages "
              f"whose\n  input sizes are genuinely unknown until a predecessor runs, "
              f"or --auto-defer to defer all of them.")

    return edge_rules


def _fmt(values):
    return "[" + ", ".join(f"{v:.4g}" for v in values) + "]"


def rule_confidence(record: dict, rule, tolerance: float) -> float:
    """
    How much of the edge's behaviour the selected rule actually explains.

    Driven by the fit residual rather than by a constant, so an edge that
    matched a rule loosely is reported as such.  The empirical fallback is
    scored by how well interpolation reproduces its own training data.
    """
    rule_id = getattr(rule, "rule_id", 8)
    confidence = 1.0

    fit = record.get("volume_fit") or {}
    if not fit.get("fitted"):
        confidence *= 0.5
    else:
        residual = float(fit.get("max_rel_err", 0.0))
        confidence *= max(0.0, 1.0 - residual / max(tolerance, 1e-9) * 0.5) if residual else 1.0
        confidence = max(confidence, 0.3)

    distinct_scales = len(set(record.get("scales", [])))
    if distinct_scales >= 3:
        pass
    elif distinct_scales == 2:
        confidence *= 0.8
    else:
        confidence *= 0.5

    if rule_id == 8:
        confidence *= 0.6  # no analytical form; extrapolation is unwarranted
    if not record.get("consistency", {}).get("consistent", True):
        confidence *= 0.8
    if record.get("max_within_instance_cv", 0.0) > tolerance:
        confidence *= 0.9  # part of the spread is not explained by scale

    return float(min(max(confidence, 0.0), 1.0))


def build_canonical_model(core_graphs: list, edge_rules: dict, vertex_series: dict,
                          scaling_type: str, tolerance: float) -> nx.DiGraph:
    """
    Annotate a core graph with the fitted rules and the observations behind them.

    Everything the projector needs is written onto the graph -- rule id, fitted
    parameters, reference scale, base metrics and multiplicities -- so a saved
    model is self-contained and can be reloaded without the instances.
    """
    model = core_graphs[0].copy()
    model.graph["scaling_type"] = scaling_type
    model.graph["tolerance"] = tolerance

    reference = min(min(info["series"]["scales"]) for info in edge_rules.values()) \
        if edge_rules else 1.0
    model.graph["reference_scale"] = reference

    for src, dst, edge_data in model.edges(data=True):
        info = edge_rules.get((src, dst))
        if info is None:
            continue
        rule, record = info["rule"], info["series"]

        base = _at_reference(record, reference)
        edge_data.update({
            EdgeAttrType.TYPE: record["pattern"],
            "rule_id": getattr(rule, "rule_id", 8),
            "rule_name": getattr(rule, "name", "Empirical"),
            "rule_params": dict(getattr(rule, "params", {}) or {}),
            "rule_expression": rule.describe(),
            "rule_confidence": info["confidence"],
            "scaling_type": scaling_type,
            "reference_scale": reference,
            "observed_scales": record["scales"],
            "observed_volumes": record["volume"],
            "observed_access_sizes": record["access_size"],
            "observed_accesses": record["accesses"],
            "observed_volume_aggregates": record["volume_aggregate"],
            "observed_num_sources": record["num_sources"],
            "observed_num_destinations": record["num_destinations"],
            "base_volume": base["volume"],
            "base_access_size": base["access_size"],
            "base_accesses": base["accesses"],
            "base_volume_aggregate": base["volume_aggregate"],
            "base_num_sources": base["num_sources"],
            "base_num_destinations": base["num_destinations"],
            "exponent_num_sources": _fit_exponent(record, "num_sources"),
            "exponent_num_destinations": _fit_exponent(record, "num_destinations"),
            "volume_pattern": record.get("volume_pattern", (UNDETERMINED, {}))[0],
            "access_size_pattern": record.get("access_size_pattern", (UNDETERMINED, {}))[0],
            "volume_aggregate_pattern": record.get("volume_aggregate_pattern", (UNDETERMINED, {}))[0],
            "output_volume_pattern": record.get("output_volume_pattern", (UNDETERMINED, {}))[0],
            "within_instance_cv": record.get("max_within_instance_cv", 0.0),
            "folded_measurements": record.get("folds", 0),
            "metric_consistency": record.get("consistency", {}),
        })
        if isinstance(rule, DeferredRule):
            edge_data["deferred_on"] = rule.dependency
            edge_data["deferral_reason"] = rule.reason

    for vertex, attrs in model.nodes(data=True):
        series = vertex_series.get(vertex)
        if not series:
            continue
        sizes = series["size"]
        scales = series["scales"]
        attrs[VertexAttrType.TYPE] = series.get("type")
        attrs["observed_scales"] = scales
        attrs["observed_sizes"] = sizes
        attrs["base_size"] = _value_at(scales, sizes, reference)
        attrs["observed_output_volumes"] = series["output_volume"]

    return model


def _at_reference(record: dict, reference: float) -> dict:
    return {metric: _value_at(record["scales"], record[metric], reference) for metric in METRICS}


def _value_at(scales, values, reference):
    for scale, value in zip(scales, values):
        if scale == reference:
            return float(value)
    return float(values[0]) if values else 0.0


def _fit_exponent(record: dict, metric: str) -> float:
    fit = fit_power_law(record.get("scales", []), record.get(metric, []))
    return float(fit["exponent"]) if fit.get("fitted") else 0.0


def build_model_for(instance_files: list, scaling_type: str, scales: list,
                    tolerance: float, defer_on: set = frozenset(),
                    auto_defer: bool = False) -> nx.DiGraph:
    """Run the whole inference pipeline for one scaling dimension."""
    banner = scaling_type.capitalize()
    print(f"\n=== Observing {banner} Scaling Instances ===")
    core_graphs, edge_series, vertex_series = observe_instances(
        instance_files, scaling_type, scales)

    print(f"\n=== Classifying {banner} Scaling Responses ===")
    classify_responses(edge_series, vertex_series, tolerance)

    print(f"\n=== Inferring Rules for {banner} Scaling ===")
    edge_rules = infer_rules(edge_series, scaling_type, tolerance, defer_on, auto_defer)

    model = build_canonical_model(core_graphs, edge_rules, vertex_series,
                                  scaling_type, tolerance)
    _report_rule_histogram(edge_rules, banner)
    return model


def _report_rule_histogram(edge_rules: dict, banner: str):
    histogram = defaultdict(int)
    deferred = 0
    for info in edge_rules.values():
        histogram[getattr(info["rule"], "rule_id", 8)] += 1
        if isinstance(info["rule"], DeferredRule):
            deferred += 1
    total = max(1, len(edge_rules))
    print(f"\n  {banner} scaling rule assignment ({len(edge_rules)} edges):")
    for rule_id in sorted(histogram):
        count = histogram[rule_id]
        print(f"    Rule {rule_id}: {count} edges ({count / total:.0%})")
    if deferred:
        print(f"    {deferred} edges deferred until their producer's size is known")


def main():
    parser = argparse.ArgumentParser(
        description="Create a canonical workflow scaling model with automatic pattern detection")
    parser.add_argument("--data-instances", nargs='+',
                        help="Workflow instances traced across data scales")
    parser.add_argument("--task-instances", nargs='+',
                        help="Workflow instances traced across task scales")
    parser.add_argument("--data-scales", nargs='+', type=float,
                        help="Scale coordinate of each --data-instances file, in order "
                             "(e.g. 1 2 4 8). Read from the filenames when omitted.")
    parser.add_argument("--task-scales", nargs='+', type=float,
                        help="Scale coordinate of each --task-instances file, in order")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                        help="Matching threshold p: the relative error a rule may leave "
                             "before an edge falls back to the empirical rule "
                             f"(default {DEFAULT_TOLERANCE:.0%}, as reported in the paper)")
    parser.add_argument("--defer-on", nargs='*', default=[],
                        help="Vertices whose output size is only known at runtime. Rules on "
                             "their out-edges are evaluated lazily (Sec. III-F), and appear "
                             "with a '*' as in the paper's tables.")
    parser.add_argument("--auto-defer", action='store_true',
                        help="Also defer every edge whose within-instance spread exceeds the "
                             "matching threshold. Off by default: in practice it flags almost "
                             "every edge, since loop iterations normally vary.")
    parser.add_argument("--output-data", default="canonical_model_data_scaling.graphml",
                        help="Output file for the data scaling model")
    parser.add_argument("--output-task", default="canonical_model_task_scaling.graphml",
                        help="Output file for the task scaling model")
    parser.add_argument("--model-in-data", help="Reuse an existing data scaling model instead of inferring one")
    parser.add_argument("--model-in-task", help="Reuse an existing task scaling model instead of inferring one")
    parser.add_argument("--project", action='store_true',
                        help="Also project a DAG at the requested target scales")
    parser.add_argument("--project-data-scale", type=float, default=2.0,
                        help="Absolute target data scale for the projection")
    parser.add_argument("--project-task-scale", type=float, default=2.0,
                        help="Absolute target task scale for the projection")
    parser.add_argument("--project-output-dir", default=None,
                        help="Directory for projection output (default: beside the model files)")
    parser.add_argument("--project-threads", type=int, default=1,
                        help="Pipeline copies to emit when unfolding (undoes space folding)")
    parser.add_argument("--project-iterations", type=int, default=1,
                        help="Loop iterations to emit per thread (undoes time folding)")
    args = parser.parse_args()

    # One dimension is enough.  Requiring both -- as this did -- locked out the
    # commoner situation: a data-scaling series is cheap to trace at several
    # sizes, while a task-scaling series means re-running the workflow at
    # different task counts, and someone who has only the first should still be
    # able to build and use the model for it.  Nothing downstream couples the two:
    # each dimension is fitted, written and projected independently.
    if not (args.data_instances or args.model_in_data or
            args.task_instances or args.model_in_task):
        parser.error("give --data-instances and/or --task-instances (or --model-in-data / "
                     "--model-in-task to reuse saved models)")

    print("=== FlowForecaster: Canonical Model Creation ===")
    print(f"Matching threshold: {args.tolerance:.0%}")

    models = {}
    for dimension, instances, explicit, output, model_in in (
            ("data", args.data_instances, args.data_scales, args.output_data, args.model_in_data),
            ("task", args.task_instances, args.task_scales, args.output_task, args.model_in_task)):
        if not (instances or model_in):
            continue
        if model_in:
            print(f"\n=== Loading {dimension} scaling model from {model_in} ===")
            models[dimension] = read_graphml_decoded(model_in)
            continue

        scales = resolve_scales(instances, explicit)
        print(f"\n{dimension.capitalize()} instances ({len(instances)}):")
        for path, scale in zip(instances, scales):
            print(f"  {scale:>6.2f}x  {path}")

        models[dimension] = build_model_for(instances, dimension, scales, args.tolerance,
                                            set(args.defer_on), args.auto_defer)
        write_graphml_encoded(models[dimension], output)
        print(f"\nSaved {dimension} scaling model to {output}")

    print("\n=== Summary ===")
    for dimension, model in models.items():
        print(f"{dimension.capitalize()} scaling model: {model.number_of_nodes()} vertices, "
              f"{model.number_of_edges()} edges")

    if args.project:
        print("\n=== Projecting DAGs ===")
        for dimension, scale, model_path in (("data", args.project_data_scale, args.output_data),
                                             ("task", args.project_task_scale, args.output_task)):
            if dimension not in models:
                continue
            out_dir = args.project_output_dir or (os.path.dirname(os.path.abspath(model_path)))
            os.makedirs(out_dir, exist_ok=True)
            model = models[dimension]

            core_path = os.path.join(out_dir, f"projected_{dimension}_scale_{scale}.core.graphml")
            dag_path = os.path.join(out_dir, f"projected_{dimension}_scale_{scale}.graphml")

            write_graphml_encoded(project_core_graph(model, scale, dimension), core_path)
            dag = unfold(model, scale, dimension, args.project_threads, args.project_iterations)
            write_graphml_encoded(dag, dag_path)

            tasks = sum(1 for _, a in dag.nodes(data=True)
                        if a.get(VertexAttrType.TYPE) == VertexType.TASK)
            files = sum(1 for _, a in dag.nodes(data=True)
                        if a.get(VertexAttrType.TYPE) == VertexType.FILE)
            print(f"  {dimension} scaling at {scale}x")
            print(f"    core-level  -> {core_path}")
            print(f"    unfolded    -> {dag_path}  "
                  f"({tasks} tasks, {files} files, {dag.number_of_edges()} edges)")

    print("\n=== Complete ===")


if __name__ == "__main__":
    main()
