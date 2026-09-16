"""
Project a workflow DAG at a target scale from a canonical scaling model.

Two things are projected, matching Sec. III-E of the paper ("projecting DAG
structure" and the dataflow over it):

1. Edge properties.  Each core edge carries a fitted rule; applying it at the
   target scale gives the predicted volume, access size and accesses.
2. DAG structure.  The core graph is a folded representation, so a projection
   has to be *unfolded* back into individual tasks and files using the
   multiplicities recorded during folding (num_sources, num_destinations).  A
   task-scaling projection that leaves the core graph's shape untouched predicts
   no new tasks, which was the previous behaviour.

The dimension being projected comes from the model itself.  A data-scaling model
holds structure fixed and scales dataflow -- which is what data scaling means --
while a task-scaling model expands the structure.
"""

import argparse
import math
import os
import sys

import networkx as nx

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "utils"))
from py_lib_flowforecaster import EdgeType, VertexType
from py_lib_flowforecaster import EdgeAttrType, VertexAttrType
from py_lib_flowforecaster import read_graphml_decoded, write_graphml_encoded

from rule_engine_auto import build_rule, VOL, ACC, NUM_ACC, VOL_AGG


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def predict_core_edges(model: nx.DiGraph, scale: float, dimension: str) -> dict:
    """
    Apply each edge's fitted rule at `scale`.

    Returns {(src, dst): predicted_metrics}, where the metrics dict also carries
    the multiplicity predicted for that edge so the unfolder can use it.
    """
    scale_key = "data_scale" if dimension == "data" else "task_scale"
    predictions = {}

    for src, dst, edge_data in model.edges(data=True):
        rule = build_rule(edge_data.get("rule_id", 8), edge_data.get("rule_params") or {})
        base_metrics = {
            VOL: _as_float(edge_data.get("base_volume"), 0.0),
            ACC: _as_float(edge_data.get("base_access_size"), 1.0),
            VOL_AGG: _as_float(edge_data.get("base_volume_aggregate"),
                               _as_float(edge_data.get("base_volume"), 0.0)),
            EdgeAttrType.NUM_SRC: _as_float(edge_data.get("base_num_sources"), 1.0),
            EdgeAttrType.NUM_DST: _as_float(edge_data.get("base_num_destinations"), 1.0),
        }
        predicted = rule.predict({scale_key: float(scale)}, base_metrics)

        reference = _as_float(edge_data.get("reference_scale"), 1.0) or 1.0
        ratio = float(scale) / reference

        # Multiplicities only respond to task scaling; data scaling changes the
        # bytes on an edge, not how many edges there are.
        if dimension == "task":
            p_dst = _as_float(edge_data.get("exponent_num_destinations"), 0.0)
            p_src = _as_float(edge_data.get("exponent_num_sources"), 0.0)
            num_dst = base_metrics[EdgeAttrType.NUM_DST] * (ratio ** p_dst)
            num_src = base_metrics[EdgeAttrType.NUM_SRC] * (ratio ** p_src)
        else:
            num_dst = base_metrics[EdgeAttrType.NUM_DST]
            num_src = base_metrics[EdgeAttrType.NUM_SRC]

        predicted[EdgeAttrType.NUM_DST] = max(1, int(round(num_dst)))
        predicted[EdgeAttrType.NUM_SRC] = max(1, int(round(predicted.get(EdgeAttrType.NUM_SRC, num_src))))

        # Only the fan-in rules state anything about the aggregate, so every
        # other rule left it unset and callers reading it got zero.  Eq. 1 defines
        # it as the sum over the in-edge set, and folding stores the mean of that
        # set alongside its cardinality, so the sum is num_sources * V -- which is
        # simply V on the sequential and fan-out edges where num_sources is 1.
        predicted.setdefault(VOL_AGG, predicted[VOL] * predicted[EdgeAttrType.NUM_SRC])
        predicted["rule_id"] = edge_data.get("rule_id", 8)
        predicted["rule_name"] = edge_data.get("rule_name", rule.name)
        predicted["rule_expression"] = edge_data.get("rule_expression", rule.describe())
        predicted[EdgeAttrType.TYPE] = edge_data.get(EdgeAttrType.TYPE, EdgeType.SEQ)
        predicted["deferred_on"] = edge_data.get("deferred_on")
        predictions[(src, dst)] = predicted

    return predictions


def project_core_graph(model: nx.DiGraph, scale: float, dimension: str) -> nx.DiGraph:
    """
    Annotate a copy of the core graph with predicted properties.

    Same shape as the model, one predicted value per core edge.  Useful for
    comparing against a measured instance edge by edge; use unfold() to get a
    DAG with individual tasks.
    """
    predictions = predict_core_edges(model, scale, dimension)
    projected = nx.DiGraph()
    _carry_metadata(projected, model, scale, dimension)

    for (src, dst), predicted in predictions.items():
        projected.add_edge(src, dst, **{
            EdgeAttrType.TYPE: predicted[EdgeAttrType.TYPE],
            EdgeAttrType.DATA_VOL: predicted[VOL],
            EdgeAttrType.ACC_SIZE: predicted[ACC],
            EdgeAttrType.ACCESSES: predicted[NUM_ACC],
            EdgeAttrType.NUM_SRC: predicted[EdgeAttrType.NUM_SRC],
            EdgeAttrType.NUM_DST: predicted[EdgeAttrType.NUM_DST],
            "rule_id": predicted["rule_id"],
            "rule_expression": predicted["rule_expression"],
        })

    # Carry vertex types across.  The old projection tested `if src not in
    # projected_dag.nodes` *after* add_edge had already created the node, so the
    # branch never ran and every projected vertex was left without a type.
    for vertex in projected.nodes:
        if vertex in model.nodes:
            projected.nodes[vertex].update({
                VertexAttrType.TYPE: model.nodes[vertex].get(VertexAttrType.TYPE),
            })
    return projected


def _carry_metadata(projected: nx.DiGraph, model: nx.DiGraph, scale: float, dimension: str):
    """
    Record what produced this graph.

    A projection is a prediction, and downstream tools -- the WfFormat converter
    in particular -- need to be able to say so rather than presenting model
    output as if it had been traced.
    """
    projected.graph.update({
        "provenance": "projected",
        "scaling_type": dimension,
        "target_scale": float(scale),
        "reference_scale": _as_float(model.graph.get("reference_scale"), 1.0),
        "tolerance": _as_float(model.graph.get("tolerance"), 0.0),
        "core_vertices": model.number_of_nodes(),
        "core_edges": model.number_of_edges(),
    })


def _instance_counts(model: nx.DiGraph, predictions: dict) -> dict:
    """
    How many real vertices each core vertex stands for at the target scale.

    Walked in topological order: a fan-out edge multiplies its consumer's count
    by the predicted out-degree, a fan-in edge divides it by the predicted
    in-degree, and a sequential edge passes the count through.
    """
    counts = {v: 1 for v in model.nodes}
    conflicts = []

    for vertex in nx.topological_sort(model):
        for _, consumer, edge_data in model.out_edges(vertex, data=True):
            predicted = predictions.get((vertex, consumer), {})
            edge_type = predicted.get(EdgeAttrType.TYPE, edge_data.get(EdgeAttrType.TYPE))
            producers = counts[vertex]

            if edge_type == EdgeType.FAN_OUT:
                implied = producers * predicted.get(EdgeAttrType.NUM_DST, 1)
            elif edge_type == EdgeType.FAN_IN:
                in_degree = max(1, predicted.get(EdgeAttrType.NUM_SRC, 1))
                implied = max(1, math.ceil(producers / in_degree))
            else:
                implied = producers

            if consumer in counts and counts[consumer] not in (1, implied):
                if counts[consumer] != implied:
                    conflicts.append((consumer, counts[consumer], implied))
            counts[consumer] = max(counts.get(consumer, 1), implied)

    for vertex, existing, implied in conflicts:
        print(f"  NOTE: predecessors of '{vertex}' imply different instance counts "
              f"({existing} vs {implied}); using {max(existing, implied)}")
    return counts


def _pair_up(n_producers: int, n_consumers: int):
    """
    Which producer instances feed which consumer instances.

    1:1 when the counts match, one-to-many for a fan-out, many-to-one for a
    fan-in, and an even block distribution otherwise.
    """
    if n_producers == n_consumers:
        return [(i, i) for i in range(n_producers)]
    if n_producers == 1:
        return [(0, j) for j in range(n_consumers)]
    if n_consumers == 1:
        return [(i, 0) for i in range(n_producers)]
    return [(i, min(n_consumers - 1, i * n_consumers // n_producers)) for i in range(n_producers)]


def _instance_name(core_name: str, index: int, total: int, prefix: str = "") -> str:
    """Name one unfolded instance; a single instance keeps the core name."""
    base = core_name if total == 1 else f"{core_name}#{index}"
    return f"{prefix}{base}" if prefix else base


def unfold(model: nx.DiGraph, scale: float, dimension: str,
           threads: int = 1, iterations: int = 1) -> nx.DiGraph:
    """
    Expand the core graph into a DAG of individual tasks and files.

    `threads` and `iterations` reproduce the space and time folds: `threads`
    independent copies of the pipeline, each a chain of `iterations` copies.
    Both default to 1, giving one pipeline at the requested scale.
    """
    predictions = predict_core_edges(model, scale, dimension)
    counts = _instance_counts(model, predictions)
    dag = nx.DiGraph()
    _carry_metadata(dag, model, scale, dimension)
    dag.graph["unfolded_threads"] = max(1, threads)
    dag.graph["unfolded_iterations"] = max(1, iterations)

    for thread in range(max(1, threads)):
        for iteration in range(max(1, iterations)):
            prefix = ""
            if threads > 1 or iterations > 1:
                prefix = f"t{thread}i{iteration}."

            for vertex, attrs in model.nodes(data=True):
                total = counts.get(vertex, 1)
                for index in range(total):
                    name = _instance_name(vertex, index, total, prefix)
                    dag.add_node(name, **{
                        VertexAttrType.TYPE: attrs.get(VertexAttrType.TYPE),
                        "core_vertex": vertex,
                    })

            for (src, dst), predicted in predictions.items():
                n_src = counts.get(src, 1)
                n_dst = counts.get(dst, 1)
                for i, j in _pair_up(n_src, n_dst):
                    attrs = {
                        EdgeAttrType.DATA_VOL: predicted[VOL],
                        EdgeAttrType.ACC_SIZE: predicted[ACC],
                        EdgeAttrType.ACCESSES: predicted[NUM_ACC],
                        EdgeAttrType.TYPE: predicted[EdgeAttrType.TYPE],
                        "rule_id": predicted["rule_id"],
                        "core_edge": f"{src} -> {dst}",
                    }
                    if predicted.get("deferred_on"):
                        attrs["deferred_on"] = predicted["deferred_on"]
                    dag.add_edge(_instance_name(src, i, n_src, prefix),
                                 _instance_name(dst, j, n_dst, prefix), **attrs)

    _assign_file_sizes(dag, model, scale, dimension)
    return dag


def _assign_file_sizes(dag: nx.DiGraph, model: nx.DiGraph, scale: float, dimension: str):
    """
    Give every projected file a size.

    A produced file's size is the volume written to it, i.e. the predicted
    volume of its incoming edge.  A root input file has no producer, so its
    observed size is scaled directly: that is what data scaling *is*, and task
    scaling leaves it alone.
    """
    for name, attrs in dag.nodes(data=True):
        if attrs.get(VertexAttrType.TYPE) != VertexType.FILE:
            continue
        in_edges = list(dag.in_edges(name, data=True))
        if in_edges:
            attrs[VertexAttrType.SIZE] = sum(_as_float(e[2].get(EdgeAttrType.DATA_VOL)) for e in in_edges)
            continue

        core = attrs.get("core_vertex")
        observed = _as_float(model.nodes.get(core, {}).get("base_size"), 0.0)
        reference = _as_float(model.graph.get("reference_scale"), 1.0) or 1.0
        ratio = float(scale) / reference
        attrs[VertexAttrType.SIZE] = observed * ratio if dimension == "data" else observed


def main():
    parser = argparse.ArgumentParser(
        description="Project a workflow DAG at a target scale from a canonical model")
    parser.add_argument("--model", required=True,
                        help="Canonical model GraphML produced by create_canonical_model_auto_scaling.py")
    parser.add_argument("--scale", type=float, required=True,
                        help="Target scale, absolute (4.0 means 4x the unscaled workflow)")
    parser.add_argument("--dimension", choices=("data", "task"),
                        help="Override the scaling dimension recorded in the model")
    parser.add_argument("--output", required=True, help="Output GraphML for the unfolded projected DAG")
    parser.add_argument("--core-output", help="Also write the core-level projection (one edge per core edge)")
    parser.add_argument("--threads", type=int, default=1,
                        help="Independent pipeline copies to emit (undoes space folding)")
    parser.add_argument("--iterations", type=int, default=1,
                        help="Loop iterations to emit per thread (undoes time folding)")
    args = parser.parse_args()

    model = read_graphml_decoded(args.model)
    dimension = args.dimension or model.graph.get("scaling_type") or "data"
    print(f"Model: {args.model} ({model.number_of_nodes()} vertices, {model.number_of_edges()} edges)")
    print(f"Projecting {dimension} scaling at {args.scale}x")

    if args.core_output:
        core = project_core_graph(model, args.scale, dimension)
        write_graphml_encoded(core, args.core_output)
        print(f"  core-level projection -> {args.core_output}")

    dag = unfold(model, args.scale, dimension, args.threads, args.iterations)
    write_graphml_encoded(dag, args.output)
    tasks = sum(1 for _, a in dag.nodes(data=True) if a.get(VertexAttrType.TYPE) == VertexType.TASK)
    files = sum(1 for _, a in dag.nodes(data=True) if a.get(VertexAttrType.TYPE) == VertexType.FILE)
    print(f"  unfolded DAG -> {args.output}")
    print(f"  {tasks} tasks, {files} files, {dag.number_of_edges()} edges")


if __name__ == "__main__":
    main()
