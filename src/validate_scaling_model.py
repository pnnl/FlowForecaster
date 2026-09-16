"""
Hold-out validation for inferred scaling models.

The protocol is the paper's: fit the model on a subset of the measured scales,
then predict the scales that were withheld and compare against what was actually
traced there.  Reporting accuracy on the scales a model was fitted to measures
nothing -- a power law through its own training points always looks good, which
is why the fit residual is already part of every rule's confidence.  What matters
is extrapolation.

Two things are scored:

  Prediction accuracy   per core edge, the relative error of predicted volume,
                        access size, and fan multiplicity at each held-out
                        scale.  Also the derived accesses A = V / S, which is
                        over-determined and therefore worth watching: the paper
                        states Rule 7's data case as A'=kA, S'=kS, V'=kV
                        simultaneously, which cannot hold under V = A * S.
  Rule recovery         if a ground-truth rule assignment is supplied (as
                        make_synthetic_instances.py writes), whether the rule
                        inferred per edge is one the generator's exponents admit.
  Projected structure   with --check-projection, the unfolded DAG at each
                        held-out scale against the DAG actually traced there:
                        task count per stage, file count, edge count.  Scoring
                        only core-edge metrics leaves the unfolder untested, and
                        under task scaling the whole claim is that new tasks are
                        predicted -- a model can get every per-edge volume right
                        while emitting the wrong number of tasks entirely.

Exits non-zero if any scored quantity misses its threshold, so it can be used as
a regression gate.
"""

import argparse
import collections
import json
import os
import re
import statistics
import sys

import networkx as nx

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "utils"))

from py_lib_flowforecaster import EdgeAttrType

from create_canonical_model_auto_scaling import build_model_for, fold_instance
from measurements import observe_edge
from project_at_scale import predict_core_edges, unfold, _as_float
from rule_engine_auto import VOL, ACC, NUM_ACC, VOL_AGG

# Quantities compared, as (label, key in the prediction, attribute of Observation).
SCORED = [
    ("volume", VOL, "volume"),
    ("access_size", ACC, "access_size"),
    ("accesses", NUM_ACC, "accesses"),
    ("volume_aggregate", VOL_AGG, "volume_aggregate"),
    ("num_sources", EdgeAttrType.NUM_SRC, "num_sources"),
    ("num_destinations", EdgeAttrType.NUM_DST, "num_destinations"),
]


def observe_core(instance_file: str, scale: float) -> dict:
    """Fold one traced instance and return {(src, dst): Observation}."""
    core = fold_instance(instance_file)
    observed = {}
    for src, dst, edge_data in core.edges(data=True):
        observed[(src, dst)] = observe_edge(core, src, dst, edge_data, scale,
                                            source=os.path.basename(instance_file))
    return observed


def relative_error(predicted: float, actual: float) -> float:
    """Relative error, with the degenerate cases named rather than divided by."""
    predicted = float(predicted)
    actual = float(actual)
    if actual == 0.0:
        return 0.0 if predicted == 0.0 else float("inf")
    return abs(predicted - actual) / abs(actual)


def score_scale(model, instance_file: str, scale: float, dimension: str,
                threshold: float) -> dict:
    """Compare the model's prediction at `scale` against the traced instance."""
    predictions = predict_core_edges(model, scale, dimension)
    observed = observe_core(instance_file, scale)

    rows = []
    only_predicted = sorted(set(predictions) - set(observed))
    only_observed = sorted(set(observed) - set(predictions))

    for edge in sorted(set(predictions) & set(observed)):
        prediction = predictions[edge]
        actual = observed[edge]
        errors = {}
        for label, pred_key, attr in SCORED:
            errors[label] = relative_error(prediction.get(pred_key, 0.0),
                                           getattr(actual, attr))
        rows.append({"edge": edge, "rule_id": prediction.get("rule_id"),
                     "errors": errors,
                     "worst": max(errors.values()),
                     "pass": max(errors[label] for label, _, _ in SCORED
                                 if label != "accesses") <= threshold})

    return {"scale": scale, "instance": os.path.basename(instance_file), "rows": rows,
            "missing_from_model": only_observed, "absent_from_trace": only_predicted}


def score_rules(model, ground_truth: dict, dimension: str) -> dict:
    """Compare inferred rule ids against the accepted sets, where supplied."""
    expected = (ground_truth.get("expected_rules") or {}).get(dimension) or {}
    if not expected:
        return {}
    rows = []
    for src, dst, edge_data in model.edges(data=True):
        key = f"{src} -> {dst}"
        accepted = expected.get(key)
        if accepted is None:
            continue
        accepted = accepted if isinstance(accepted, list) else [accepted]
        inferred = int(_as_float(edge_data.get("rule_id"), 8))
        rows.append({"edge": key, "inferred": inferred, "accepted": accepted,
                     "pass": inferred in accepted})
    unmatched = sorted(set(expected) - {row["edge"] for row in rows})
    return {"rows": rows, "unmatched": unmatched}


SCAFFOLD_DEFAULT = "dummy_task"

RE_TASKID = re.compile(r"_taskid\d+")
RE_FOLD = re.compile(r"iter-(\d+)\.thrd-(\d+)")


def fold_shape(instance_file: str):
    """
    Recover (threads, iterations) from the traced-instance naming convention.

    The unfolder has to be asked for the same shape the instance was traced at or
    the comparison is meaningless -- it would emit a different number of pipeline
    copies and every stage count would be off by that factor.
    """
    match = RE_FOLD.search(os.path.basename(instance_file))
    if not match:
        return None, None
    return int(match.group(2)), int(match.group(1))


def traced_structure(instance_file: str, scaffold: str):
    """
    Count what was actually traced, per workflow stage.

    `scaffold` names the iteration-chaining convention (dummy_task).  Folding
    absorbs it into the time dimension, so the core model has no vertex for it and
    the unfolder re-expresses it as `iterations` copies of the pipeline.  It and
    its incident edges are therefore excluded from both sides rather than counted
    as a miss -- and reported, so the exclusion stays visible instead of quietly
    flattering the result.
    """
    graph = nx.read_graphml(instance_file)
    scaffold_nodes = {n for n in graph.nodes if scaffold and scaffold in n}
    stages = collections.Counter()
    tasks = files = 0
    for name, attrs in graph.nodes(data=True):
        if name in scaffold_nodes:
            continue
        if attrs.get("type") == "task":
            tasks += 1
            stages[RE_TASKID.sub("", name)] += 1
        else:
            files += 1
    edges = sum(1 for u, v in graph.edges
                if u not in scaffold_nodes and v not in scaffold_nodes)
    return {"stages": stages, "tasks": tasks, "files": files, "edges": edges,
            "scaffold_tasks": len(scaffold_nodes),
            "scaffold_edges": graph.number_of_edges() - edges}


def projected_structure(model, scale: float, dimension: str,
                        threads: int, iterations: int):
    """Count what the unfolded projection emits, per core stage."""
    dag = unfold(model, scale, dimension, threads, iterations)
    stages = collections.Counter()
    tasks = files = 0
    for name, attrs in dag.nodes(data=True):
        if attrs.get("type") == "task":
            tasks += 1
            stages[attrs.get("core_vertex", name)] += 1
        else:
            files += 1
    return {"stages": stages, "tasks": tasks, "files": files,
            "edges": dag.number_of_edges()}


def score_structure(model, instance_file: str, scale: float, dimension: str,
                    threads: int, iterations: int, scaffold: str) -> dict:
    """Compare the projected DAG's shape against the traced DAG's shape."""
    traced = traced_structure(instance_file, scaffold)
    predicted = projected_structure(model, scale, dimension, threads, iterations)

    rows = []
    for stage in sorted(set(traced["stages"]) | set(predicted["stages"])):
        actual = traced["stages"].get(stage, 0)
        guess = predicted["stages"].get(stage, 0)
        rows.append({"stage": stage, "actual": actual, "predicted": guess,
                     "pass": actual == guess})
    totals = {key: {"actual": traced[key], "predicted": predicted[key],
                    "pass": traced[key] == predicted[key]}
              for key in ("tasks", "files", "edges")}
    return {"scale": scale, "instance": os.path.basename(instance_file),
            "threads": threads, "iterations": iterations,
            "rows": rows, "totals": totals,
            "scaffold": scaffold,
            "scaffold_tasks": traced["scaffold_tasks"],
            "scaffold_edges": traced["scaffold_edges"],
            "pass": all(r["pass"] for r in rows) and all(t["pass"] for t in totals.values())}


def _percentile(values, fraction):
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def report(results: list, rule_score: dict, threshold: float,
           structure: list = None) -> bool:
    """Print the scorecard; return True if everything met its threshold."""
    ok = True

    print("\n=== Prediction accuracy on held-out scales ===")
    print(f"    threshold: {threshold:.0%} relative error\n")
    all_errors = []
    for result in results:
        rows = result["rows"]
        if not rows:
            print(f"  scale {result['scale']:g}x  ({result['instance']}): no comparable edges")
            ok = False
            continue
        worst = [row["worst"] for row in rows]
        finite = [w for w in worst if w != float("inf")]
        passed = sum(1 for row in rows if row["pass"])
        all_errors.extend(finite)
        print(f"  scale {result['scale']:g}x  ({result['instance']})")
        print(f"    {passed}/{len(rows)} edges within {threshold:.0%}"
              f"   median {statistics.median(finite) if finite else float('nan'):.2%}"
              f"   p90 {_percentile(finite, 0.9):.2%}"
              f"   max {max(worst):.2%}")
        for row in rows:
            if row["pass"]:
                continue
            ok = False
            src, dst = row["edge"]
            detail = "  ".join(f"{label} {row['errors'][label]:.1%}"
                               for label, _, _ in SCORED
                               if row["errors"][label] > threshold)
            print(f"      MISS  Rule {row['rule_id']}  ({src}) -> ({dst})   {detail}")
        for edge in result["missing_from_model"]:
            ok = False
            print(f"      MISS  edge traced at this scale but absent from the model: {edge}")
        for edge in result["absent_from_trace"]:
            ok = False
            print(f"      MISS  edge predicted but not traced at this scale: {edge}")

    if all_errors:
        within = sum(1 for e in all_errors if e <= threshold)
        print(f"\n  overall: {within}/{len(all_errors)} within {threshold:.0%}, "
              f"median {statistics.median(all_errors):.2%}, "
              f"p90 {_percentile(all_errors, 0.9):.2%}")

    if rule_score:
        rows = rule_score["rows"]
        correct = sum(1 for row in rows if row["pass"])
        print(f"\n=== Rule recovery ===\n")
        print(f"  {correct}/{len(rows)} edges assigned a rule the generator admits\n")
        for row in rows:
            mark = "ok  " if row["pass"] else "WRONG"
            accepted = "/".join(str(r) for r in row["accepted"])
            print(f"  {mark}  inferred Rule {row['inferred']}  "
                  f"(accepted: {accepted})  {row['edge']}")
            if not row["pass"]:
                ok = False
        for edge in rule_score["unmatched"]:
            ok = False
            print(f"  WRONG  ground truth names an edge the model does not have: {edge}")

    for score in structure or []:
        print(f"\n=== Projected DAG structure at {score['scale']:g}x ===")
        print(f"    unfolded as {score['threads']} threads x {score['iterations']} "
              f"iterations, against {score['instance']}")
        if score["scaffold_tasks"]:
            print(f"    excluding the '{score['scaffold']}' scaling scaffold from both "
                  f"sides ({score['scaffold_tasks']} tasks, "
                  f"{score['scaffold_edges']} incident edges): folding absorbs it into "
                  f"the iteration count, so the core model has no vertex for it")
        print()
        for key, total in score["totals"].items():
            mark = "ok  " if total["pass"] else "MISS"
            print(f"  {mark}  total {key:<6} traced {total['actual']:>6} "
                  f" predicted {total['predicted']:>6}")
        print()
        for row in score["rows"]:
            mark = "ok  " if row["pass"] else "MISS"
            print(f"  {mark}  {row['stage']:<24} traced {row['actual']:>6} "
                  f" predicted {row['predicted']:>6}")
        if not score["pass"]:
            ok = False

    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Fit a scaling model on some scales and score it on the rest",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--instances", nargs='+', required=True,
                        help="traced instances, in the same order as --scales")
    parser.add_argument("--scales", nargs='+', type=float, required=True,
                        help="the scale each instance was traced at")
    parser.add_argument("--dimension", choices=("data", "task"), required=True)
    parser.add_argument("--train", nargs='+', type=float,
                        help="scales to fit on (default: all but the largest)")
    parser.add_argument("--test", nargs='+', type=float,
                        help="scales to score on (default: whatever --train leaves)")
    parser.add_argument("--tolerance", type=float, default=0.10,
                        help="matching threshold used while inferring rules")
    parser.add_argument("--threshold", type=float, default=0.10,
                        help="relative error a prediction must stay within to pass")
    parser.add_argument("--ground-truth",
                        help="ground_truth.json from make_synthetic_instances.py, "
                             "to also score which rule was recovered per edge")
    parser.add_argument("--check-projection", action="store_true",
                        help="also unfold the model at each held-out scale and compare the "
                             "resulting DAG's shape against the instance traced there")
    parser.add_argument("--project-threads", type=int,
                        help="threads to unfold with (default: read from the "
                             "'thrd-<N>' part of the instance filename)")
    parser.add_argument("--project-iterations", type=int,
                        help="iterations to unfold with (default: read from the "
                             "'iter-<N>' part of the instance filename)")
    parser.add_argument("--scaffold-task", default=SCAFFOLD_DEFAULT,
                        help="task name substring for the iteration-chaining scaffold "
                             f"folding absorbs (default: {SCAFFOLD_DEFAULT!r}; "
                             "pass '' to compare it too)")
    parser.add_argument("--json-out", help="write the full scorecard here")
    args = parser.parse_args()

    if len(args.instances) != len(args.scales):
        parser.error(f"{len(args.instances)} instances but {len(args.scales)} scales")

    by_scale = dict(zip(args.scales, args.instances))
    train = args.train or sorted(by_scale)[:-1]
    test = args.test or [s for s in sorted(by_scale) if s not in train]

    unknown = [s for s in list(train) + list(test) if s not in by_scale]
    if unknown:
        parser.error(f"no instance given for scale(s) {unknown}")
    if len(train) < 2:
        parser.error("fitting needs at least two distinct scales")
    if not test:
        parser.error("no scales left to test on; withhold at least one")
    overlap = sorted(set(train) & set(test))
    if overlap:
        print(f"NOTE: scale(s) {overlap} are in both --train and --test. Accuracy "
              f"there measures fit, not prediction.")

    print(f"=== {args.dimension.capitalize()} scaling: "
          f"fit on {sorted(train)}, predict {sorted(test)} ===")

    model = build_model_for([by_scale[s] for s in sorted(train)], args.dimension,
                            sorted(train), args.tolerance)

    results = [score_scale(model, by_scale[s], s, args.dimension, args.threshold)
               for s in sorted(test)]

    rule_score = {}
    if args.ground_truth:
        with open(args.ground_truth) as fh:
            rule_score = score_rules(model, json.load(fh), args.dimension)

    structure = []
    if args.check_projection:
        for scale in sorted(test):
            instance = by_scale[scale]
            threads, iterations = fold_shape(instance)
            threads = args.project_threads or threads
            iterations = args.project_iterations or iterations
            if not threads or not iterations:
                parser.error(f"cannot tell the fold shape of {os.path.basename(instance)}; "
                             "pass --project-threads and --project-iterations")
            structure.append(score_structure(model, instance, scale, args.dimension,
                                             threads, iterations, args.scaffold_task))

    ok = report(results, rule_score, args.threshold, structure)

    if args.json_out:
        payload = {"dimension": args.dimension, "train": sorted(train),
                   "test": sorted(test), "tolerance": args.tolerance,
                   "threshold": args.threshold, "passed": ok,
                   "accuracy": [{**r, "rows": [{**row, "edge": list(row["edge"])}
                                               for row in r["rows"]]} for r in results],
                   "rule_recovery": rule_score,
                   "structure": [{**s, "rows": s["rows"],
                                  "stages_traced": dict(s.pop("stages", {}) or {})}
                                 for s in structure]}
        with open(args.json_out, "w") as fh:
            json.dump(payload, fh, indent=2, default=str)
            fh.write("\n")
        print(f"\nScorecard -> {args.json_out}")

    print(f"\n=== {'PASS' if ok else 'FAIL'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
