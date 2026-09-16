#!/usr/bin/env python3
"""Convert FlowForecaster GraphML task-property graphs to WfCommons WfFormat JSON.

FlowForecaster stores a workflow instance as a *bipartite* directed property
graph: `file` nodes (attribute `size`) and `task` nodes, with `file -> task`
edges for reads and `task -> file` edges for writes.  Every edge carries
`data_volume` and `access_size`.

WfFormat (https://github.com/wfcommons/WfFormat, the format served by
https://wfinstances.ics.hawaii.edu) stores the same DAG task-centric: a list of
tasks, each with `parents`/`children` (task-to-task) plus `inputFiles`/
`outputFiles`, and a separate list of files with `sizeInBytes`.

The two are isomorphic for the `specification` half of WfFormat:

    task t                      -> specification.tasks[t]
    file f, size s              -> specification.files[f].sizeInBytes = s
    edge f -> t                 -> tasks[t].inputFiles += f
    edge t -> f                 -> tasks[t].outputFiles += f
    t1 -> f -> t2               -> tasks[t2].parents += t1, tasks[t1].children += t2

What does *not* map: WfFormat has no per-edge properties, so `data_volume` and
`access_size` -- the quantities FlowForecaster actually models -- have nowhere
to live in standard WfFormat.  They are preserved under a top-level
`flowforecaster` extension key (JSON Schema `additionalProperties` is open, so
the instance still validates).  Pass --strict to drop the extension and emit
nothing but standard WfFormat.

The `execution` half of WfFormat (task runtimes, makespan, machines) is *not*
emitted: FlowForecaster graphs carry no timing or machine data and inventing it
would be fabrication.  `execution` is optional in the schema; only
`specification` is required.
"""

import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys

import networkx as nx

SCHEMA_VERSION = "1.6"

# WfFormat $defs/taskId and the file-id pattern, for a pre-flight check on ids.
RE_TASK_ID = re.compile(r"^[0-9a-zA-Z_.#:/-]+$")
RE_FILE_ID = re.compile(r"^[0-9a-zA-Z-_./:#]*$")

# Filename conventions used by the FlowForecaster instance generators.
RE_SCALE = re.compile(r"_(data|task)_scale_([0-9.]+)$")
RE_NX = re.compile(r"\.(data|task)_([0-9.]+)x$")
# project_at_scale.py writes "projected_<dim>_scale_<k>[.core]".
RE_PROJECTED = re.compile(r"^projected_(data|task)_scale_([0-9.]+)(\.core)?$")


def scalar(value):
    """Parse a GraphML attribute as a number, or return None if it is not one.

    Concrete instances carry plain numbers.  Canonical *models* carry rule
    expressions and nested per-observation arrays (e.g.
    "[[np.float64(309.5), ...], ...]") in the same attributes, and those must
    never be coerced -- silently turning them into 0 would fabricate data.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def number(value):
    """Exact numeric value: int when integral, float otherwise.

    Some GraphML edges declare attr.type="long" but hold fractions (a fan-in
    volume of 6.666666666666667, say).  Rounding those would corrupt the very
    ratios a scaling series exists to express, so the extension keeps them
    exactly; only `sizeInBytes`, which the schema types as an integer, rounds.
    """
    parsed = scalar(value)
    if parsed is None:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def classify(graph):
    """Return (kind, reason); kind is "instance", "model" or "unsupported"."""
    types = collections.Counter(d.get("type") for _, d in graph.nodes(data=True))
    if None in types:
        return "model", ("%d node(s) have no `type` attribute "
                         "(projected/abstract model, not an instance)" % types[None])
    unknown = set(types) - {"file", "task"}
    if unknown:
        return "unsupported", "unsupported node type(s): %s" % ", ".join(sorted(unknown))
    if not types.get("task"):
        return "unsupported", "no task nodes"
    for u, v in graph.edges():
        tu, tv = graph.nodes[u]["type"], graph.nodes[v]["type"]
        if tu == tv:
            return "unsupported", ("edge %s -> %s connects two %s nodes "
                                   "(graph is not bipartite)" % (u, v, tu))
    if not nx.is_directed_acyclic_graph(graph):
        return "unsupported", "graph is cyclic"

    # A canonical model looks bipartite but stores expressions, not values.
    for node, d in graph.nodes(data=True):
        if d["type"] == "file" and "size" in d and scalar(d["size"]) is None:
            return "model", ("file `%s` has a non-scalar size (%.40s...): this is a "
                             "canonical model, not an instance" % (node, d["size"]))
    for u, v, d in graph.edges(data=True):
        for attr in ("data_volume", "access_size"):
            if attr in d and scalar(d[attr]) is None:
                return "model", ("edge %s -> %s has a non-scalar %s (%.40s...): this is "
                                 "a canonical model, not an instance" % (u, v, attr, d[attr]))
    return "instance", None


def scaling_of(stem):
    """Recover (dimension, factor) from the generator's filename convention."""
    for pattern in (RE_SCALE, RE_NX, RE_PROJECTED):
        match = pattern.search(stem)
        if match:
            return match.group(1), float(match.group(2))
    return None, None


def projection_scaling_of(graph, stem):
    """
    Recover (dimension, target scale) for a projected DAG.

    Ask the graph before the file name.  A projection records its own dimension
    and target scale in its metadata, and that is the authoritative answer;
    project_at_scale.py names its output from --output, so the name need not
    mention the scale at all.  Insisting on a name marker -- as this did --
    rejected every projection written to a path the user chose, which is the
    normal case, and the graph was sitting there holding the answer.
    """
    dimension = graph.graph.get("scaling_type")
    factor = scalar(graph.graph.get("target_scale"))
    if dimension in ("data", "task") and factor:
        return dimension, float(factor)
    return scaling_of(stem)


def task_levels(parents):
    """Level of a task = longest path from a source, as WfCommons computes it."""
    level = {}

    def visit(task):
        if task not in level:
            level[task] = 0 if not parents[task] else 1 + max(visit(p) for p in parents[task])
        return level[task]

    for task in parents:
        visit(task)
    return level


def git_author():
    """Default WfFormat `author` to whoever git says is doing the conversion."""
    def config(key):
        try:
            out = subprocess.run(["git", "config", "--get", key],
                                 capture_output=True, text=True, timeout=5)
            return out.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None

    return {"name": config("user.name"), "email": config("user.email")}


def add_warning(instance, text):
    """
    Append a caveat to the instance's warning list.

    A list rather than a single string because two unrelated concerns write here:
    the provenance warning that an instance is predicted rather than measured, and
    a note about file sizes that could not be scaled.  These used to share one
    `warning` key, so a projection that also had an unscalable file size lost the
    provenance warning entirely -- the one caveat that must never go missing.
    """
    warnings = instance["flowforecaster"].setdefault("warnings", [])
    if text not in warnings:
        warnings.append(text)


def convert(graph, name, description, source, author, size_multiplier=1,
            strict=False, projection=None):
    tasks = [n for n, d in graph.nodes(data=True) if d["type"] == "task"]
    files = [n for n, d in graph.nodes(data=True) if d["type"] == "file"]

    inputs = {t: sorted(graph.predecessors(t)) for t in tasks}
    outputs = {t: sorted(graph.successors(t)) for t in tasks}

    # Task-to-task dependencies: t1 -> t2 iff t1 writes a file that t2 reads.
    parents = {t: set() for t in tasks}
    children = {t: set() for t in tasks}
    for f in files:
        writers = list(graph.predecessors(f))
        readers = list(graph.successors(f))
        for w in writers:
            for r in readers:
                if w != r:
                    parents[r].add(w)
                    children[w].add(r)

    spec_tasks = [
        {
            "name": re.sub(r"_?taskid\d+$", "", t) or t,
            "id": t,
            "parents": sorted(parents[t]),
            "children": sorted(children[t]),
            "inputFiles": inputs[t],
            "outputFiles": outputs[t],
        }
        for t in sorted(tasks)
    ]
    spec_files = []
    unscalable_sizes = {}
    rounded_sizes = {}
    for f in sorted(files):
        raw = graph.nodes[f].get("size")
        exact = scalar(raw)
        if exact is None:
            if raw is not None:
                unscalable_sizes[f] = str(raw)
        elif not exact.is_integer():
            rounded_sizes[f] = exact
        spec_files.append({
            "id": f,
            "sizeInBytes": (0 if exact is None else int(round(exact))) * size_multiplier,
        })

    level = task_levels({t: parents[t] for t in tasks})
    widths = collections.Counter(level.values())
    metrics = {
        "numberOfTasks": len(spec_tasks),
        "numberOfFiles": len(spec_files),
        "sumOfFileSizesInBytes": sum(f["sizeInBytes"] for f in spec_files),
        "numberOfLevels": max(widths) + 1 if widths else 0,
        "minimumWidth": min(widths.values()) if widths else 0,
        "maximumWidth": max(widths.values()) if widths else 0,
    }

    instance = {
        "name": name,
        "description": description,
        "createdAt": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "schemaVersion": SCHEMA_VERSION,
        "author": author,
        "workflow": {
            "specification": {
                "tasks": spec_tasks,
                "files": spec_files,
                "metrics": metrics,
            }
        },
    }
    if strict:
        return instance

    dimension, factor = scaling_of(os.path.splitext(os.path.basename(source))[0])
    dataflow = []
    for u, v, d in sorted(graph.edges(data=True)):
        is_read = graph.nodes[u]["type"] == "file"
        entry = {
            "task": v if is_read else u,
            "file": u if is_read else v,
            "role": "read" if is_read else "write",
        }
        # Numbers land in dataVolume/accessSize; anything else (a canonical
        # model's rule expressions) is carried through verbatim as a string.
        for attr, key in (("data_volume", "dataVolume"), ("access_size", "accessSize"),
                          ("accesses", "accessCount")):
            if attr not in d:
                continue
            exact = number(d[attr])
            if exact is None:
                entry[key + "Expression"] = str(d[attr])
            else:
                entry[key] = exact
        # A projected edge says which rule produced it, so the prediction can be
        # traced back to the rule that made it.
        for attr, key in (("rule_id", "ruleId"), ("core_edge", "coreEdge"),
                          ("deferred_on", "deferredOn")):
            if attr in d:
                entry[key] = number(d[attr]) if attr == "rule_id" else str(d[attr])
        extra = {k: v2 for k, v2 in sorted(d.items())
                 if k not in ("data_volume", "access_size", "accesses",
                              "rule_id", "core_edge", "deferred_on")}
        if extra:
            entry["attributes"] = {k: str(v2) for k, v2 in extra.items()}
        dataflow.append(entry)
    read = collections.Counter()
    written = collections.Counter()
    for e in dataflow:
        (read if e["role"] == "read" else written)[e["task"]] += e.get("dataVolume", 0)

    instance["flowforecaster"] = {
        "sourceGraphml": source,
        "scalingDimension": dimension,
        "scalingFactor": factor,
        "units": (
            "FlowForecaster property graphs carry abstract, unitless data "
            "quantities, not measured bytes. `sizeInBytes`, `dataVolume` and "
            "`accessSize` reproduce the GraphML values verbatim (times "
            "--size-multiplier, here %d) so that ratios across a scaling "
            "series are exact; they are not real byte counts."
        )
        % size_multiplier,
        "taskDataVolume": {
            t: {"read": read[t], "written": written[t]} for t in sorted(tasks)
        },
        "dataflow": dataflow,
    }
    if projection:
        rules = collections.Counter(e["ruleId"] for e in dataflow if "ruleId" in e)
        deferred = sorted({e["deferredOn"] for e in dataflow if "deferredOn" in e})
        instance["flowforecaster"].update({
            "provenance": "projected",
            "projection": {
                "model": projection.get("model"),
                "dimension": projection.get("dimension"),
                "targetScale": projection.get("scale"),
                "referenceScale": projection.get("reference_scale"),
                "rulesApplied": {"Rule %s" % k: v for k, v in sorted(rules.items())},
                "deferredOn": deferred,
                "coreVertices": projection.get("core_vertices"),
                "coreEdges": projection.get("core_edges"),
            },
        })
        add_warning(instance,
                    "PREDICTED, NOT MEASURED. Every task, file, size and data volume "
                    "in this instance was produced by applying an inferred scaling "
                    "model at %s scale %g; none of it was traced. Do not treat it as "
                    "an observation." % (projection.get("dimension"), projection.get("scale")))

    if rounded_sizes:
        instance["flowforecaster"]["exactFileSizes"] = rounded_sizes
    if unscalable_sizes:
        instance["flowforecaster"]["fileSizeExpressions"] = unscalable_sizes
        add_warning(instance,
                    "%d file(s) carry a non-scalar `size` in the source GraphML; their "
                    "`sizeInBytes` is reported as 0 and the original expression is kept "
                    "in `fileSizeExpressions`." % len(unscalable_sizes))
    return instance


def check(instance):
    """Structural check of the emitted instance (no jsonschema dependency)."""
    problems = []
    for key in ("name", "schemaVersion", "workflow"):
        if key not in instance:
            problems.append("missing required top-level key `%s`" % key)
    spec = instance["workflow"]["specification"]
    file_ids = {f["id"] for f in spec["files"]}
    task_ids = {t["id"] for t in spec["tasks"]}
    if len(file_ids) != len(spec["files"]):
        problems.append("duplicate file ids")
    if len(task_ids) != len(spec["tasks"]):
        problems.append("duplicate task ids")
    for f in spec["files"]:
        if not RE_FILE_ID.match(f["id"]):
            problems.append("file id violates schema pattern: %s" % f["id"])
        if not isinstance(f["sizeInBytes"], int) or f["sizeInBytes"] < 0:
            problems.append("bad sizeInBytes for %s" % f["id"])
    edges = set()
    for t in spec["tasks"]:
        if not RE_TASK_ID.match(t["id"]):
            problems.append("task id violates schema pattern: %s" % t["id"])
        for f in t["inputFiles"] + t["outputFiles"]:
            if f not in file_ids:
                problems.append("task %s references unknown file %s" % (t["id"], f))
        for p in t["parents"]:
            if p not in task_ids:
                problems.append("task %s has unknown parent %s" % (t["id"], p))
            edges.add((p, t["id"]))
        for c in t["children"]:
            if c not in task_ids:
                problems.append("task %s has unknown child %s" % (t["id"], c))
    for t in spec["tasks"]:
        for c in t["children"]:
            if (t["id"], c) not in edges:
                problems.append("child %s of %s not mirrored in its parents" % (c, t["id"]))
    dag = nx.DiGraph(sorted(edges))
    dag.add_nodes_from(task_ids)
    if not nx.is_directed_acyclic_graph(dag):
        problems.append("task graph is cyclic")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="GraphML instance files")
    ap.add_argument("-o", "--outdir", default="wfinstances",
                    help="directory for the emitted JSON (default: wfinstances)")
    ap.add_argument("--flat", action="store_true",
                    help="write every JSON into --outdir instead of mirroring input dirs")
    ap.add_argument("--strict", action="store_true",
                    help="emit standard WfFormat only; drop the `flowforecaster` extension")
    ap.add_argument("--size-multiplier", type=int, default=1,
                    help="multiply every file size / data volume by this factor (default: 1)")
    ap.add_argument("--name-prefix", default="1000genome-flowforecaster",
                    help="prefix for the WfFormat `name` field")
    ap.add_argument("--manifest", default=None,
                    help="also write a manifest of all converted instances to this path")
    ap.add_argument("--author-name", default=None,
                    help="WfFormat author name (default: git config user.name)")
    ap.add_argument("--author-email", default=None,
                    help="WfFormat author email (default: git config user.email)")
    ap.add_argument("--author-institution", default="Pacific Northwest National Laboratory",
                    help="WfFormat author institution")
    ap.add_argument("--author-country", default="US", help="WfFormat author country")
    ap.add_argument("--from-projection", action="store_true",
                    help="treat the inputs as projections from project_at_scale.py: mark the "
                         "emitted JSON as predicted rather than measured, and record the "
                         "model, target scale and per-edge rule attribution")
    ap.add_argument("--projection-model", default=None,
                    help="with --from-projection, the canonical model the projection came from "
                         "(recorded in the output for provenance)")
    ap.add_argument("--include-models", action="store_true",
                    help="also convert canonical/projected models (their rule expressions "
                         "are preserved verbatim, but sizes/volumes are reported as 0)")
    args = ap.parse_args()

    author = git_author()
    if args.author_name:
        author["name"] = args.author_name
    if args.author_email:
        author["email"] = args.author_email
    if not author["name"] or not author["email"]:
        ap.error("no author identity: set git config user.name/user.email, or pass "
                 "--author-name and --author-email (the schema requires both)")
    author["institution"] = args.author_institution
    author["country"] = args.author_country

    manifest, skipped, failed = [], [], 0
    for path in args.inputs:
        graph = nx.read_graphml(path)
        kind, reason = classify(graph)
        if kind == "unsupported" or (kind == "model" and not args.include_models):
            skipped.append((path, reason))
            print("skip  %-62s %s" % (os.path.basename(path), reason), file=sys.stderr)
            continue

        stem = os.path.splitext(os.path.basename(path))[0]
        name = "%s-%s" % (args.name_prefix, re.sub(r"[^0-9a-zA-Z]+", "-", stem).strip("-"))
        dimension, factor = scaling_of(stem)
        projection = None
        if args.from_projection:
            dimension, factor = projection_scaling_of(graph, stem)
            if dimension is None:
                print("skip  %-62s --from-projection given but neither the graph metadata "
                      "nor the filename records a target scale" % os.path.basename(path),
                      file=sys.stderr)
                skipped.append((path, "no target scale in graph metadata or filename"))
                continue
            projection = {
                "model": args.projection_model,
                "dimension": dimension,
                "scale": factor,
                "reference_scale": scalar(graph.graph.get("reference_scale")),
                "core_vertices": len({d["core_vertex"] for _, d in graph.nodes(data=True)
                                      if "core_vertex" in d}) or None,
                "core_edges": len({d["core_edge"] for _, _, d in graph.edges(data=True)
                                   if "core_edge" in d}) or None,
            }
            described = "predicted at %s scale %g" % (dimension, factor)
            description = (
                "Workflow DAG PREDICTED by FlowForecaster at %s scale %g, unfolded from "
                "a canonical scaling model. Not a traced instance: every value here is a "
                "model output. Converted to WfFormat from %s. Data quantities are abstract "
                "FlowForecaster units, not measured bytes." % (dimension, factor, path)
            )
        else:
            described = (
                "%s scaling instance (factor %g)" % (dimension, factor)
                if dimension else "base instance"
            )
            description = (
                "1000 Genomes workflow property graph from FlowForecaster (%s), "
                "converted to WfFormat from %s. Data quantities are abstract "
                "FlowForecaster units, not measured bytes." % (described, path)
            )

        instance = convert(graph, name, description, path, author,
                           size_multiplier=args.size_multiplier, strict=args.strict,
                           projection=projection)
        problems = check(instance)
        if problems:
            failed += 1
            for p in problems:
                print("FAIL  %-62s %s" % (os.path.basename(path), p), file=sys.stderr)
            continue

        # Group outputs by the top-level source directory (synthetic_data/1000Genomes
        # -> "synthetic_data") so the layout mirrors where the GraphML came from.
        # Note this follows the *current* location of the inputs: moving a source
        # tree changes the group, so --flat plus an explicit --outdir is the way to
        # rewrite an existing group in place.
        rel = os.path.relpath(os.path.dirname(os.path.abspath(path)), os.getcwd())
        top = "" if rel in (".", "") or rel.startswith("..") else rel.split(os.sep)[0]
        subdir = "" if args.flat else top
        if kind == "model":
            subdir = os.path.join(subdir, "models")
        outdir = os.path.join(args.outdir, subdir)
        os.makedirs(outdir, exist_ok=True)
        outpath = os.path.join(outdir, stem + ".json")
        with open(outpath, "w") as fh:
            json.dump(instance, fh, indent=2)
            fh.write("\n")

        m = instance["workflow"]["specification"]["metrics"]
        manifest.append({
            "file": os.path.relpath(outpath, args.outdir),
            "name": name,
            "source": path,
            "scalingDimension": dimension,
            "scalingFactor": factor,
            "kind": "projection" if args.from_projection else kind,
            "metrics": m,
        })
        print("ok    %-62s -> %-24s %3d tasks %3d files %d levels"
              % (os.path.basename(path), os.path.basename(outpath),
                 m["numberOfTasks"], m["numberOfFiles"], m["numberOfLevels"]))

    if args.manifest and manifest:
        os.makedirs(os.path.dirname(os.path.abspath(args.manifest)), exist_ok=True)
        with open(args.manifest, "w") as fh:
            json.dump({"schemaVersion": SCHEMA_VERSION,
                       "count": len(manifest),
                       "instances": manifest}, fh, indent=2)
            fh.write("\n")

    print("\n%d converted, %d skipped, %d failed" % (len(manifest), len(skipped), failed),
          file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
