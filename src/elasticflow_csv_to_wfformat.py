#!/usr/bin/env python3
"""Convert an ElasticFlow 1000 Genomes dataflow CSV to WfCommons WfFormat JSON.

ElasticFlow (https://github.com/PerfLab-EXaCT/ElasticFlow) records a workflow
run as one row per (task instance, file, I/O operation):

    operation  read | write | cp | scp | none
    taskName   workflow stage (individuals, sifting, frequency, ...)
    taskPID    task instance id, e.g. "28566-dc257"
    fileName   the file touched
    aggregateFilesizeMBtask   MiB moved by that task for that operation
    transferSize, opCount, totalTime, trMiB, storageType

This is a bipartite task/file dataflow, the same shape as a FlowForecaster
property graph, so it maps onto WfFormat's `specification` the same way:
`read` rows become inputFiles, `write` rows outputFiles, and a task that writes
a file is the parent of every task that reads it.

Three properties of the source data drive the design, all verified by
--self-check:

1. `numNodes` (2, 5, 10) does NOT vary the DAG.  The three slices are
   identical row-for-row apart from `numNodes`, `tasksPerNode` and the
   `estimated_*` model outputs: one measured run evaluated under three
   hypothetical node counts for the storage-placement model.  One slice is
   converted and the rest are asserted identical.

2. `totalTime` is I/O transfer time, not task runtime -- `trMiB` equals
   `aggregateFilesizeMBtask / totalTime` on every row.  So no WfFormat
   `execution` block is emitted: there is no wall-clock runtime to put in
   `runtimeInSeconds`, and inventing one would be fabrication.  The measured
   I/O goes in the `elasticflow` extension instead.

3. `aggregateFilesizeMBtask` is a per-task, per-operation aggregate, not a file
   size.  Every write group is a single file, so a written file's size is a
   direct measurement; files never written are solved from read groups that
   contain exactly one unknown.  Each file records how its size was obtained.

`cp`/`scp`/`none` rows carry no taskPID -- they are stage-in/stage-out data
movement, not workflow tasks -- so they are summarised in the extension rather
than turned into tasks.
"""

import argparse
import collections
import csv
import datetime
import json
import os
import re
import statistics
import sys

from graphml_to_wfformat import SCHEMA_VERSION, check, git_author, task_levels

MIB = 1024 * 1024   # `trMiB` == aggregateFilesizeMBtask / totalTime, so the
                    # column's "MB" is MiB; sizes convert with 1024**2.
IO_OPS = ("read", "write")
RE_FILE_ID = re.compile(r"^[0-9a-zA-Z-_./:#]*$")
RE_TASK_ID = re.compile(r"^[0-9a-zA-Z_.#:/-]+$")


def load(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def dag_key(row):
    """Everything that defines the DAG, excluding the placement columns."""
    return (row["operation"], row["taskName"], row["taskPID"], row["fileName"],
            row["aggregateFilesizeMBtask"], row["transferSize"], row["opCount"],
            row["totalTime"], row["stageOrder"], row["prevTask"])


def pick_slice(rows, verbose=True):
    """Return one numNodes slice, asserting every slice holds the same DAG."""
    slices = collections.defaultdict(list)
    for r in rows:
        slices[r["numNodes"]].append(r)
    keys = {nn: {dag_key(r) for r in rs} for nn, rs in slices.items()}
    names = sorted(keys, key=lambda x: int(x))
    base = keys[names[0]]
    for nn in names[1:]:
        if keys[nn] != base:
            raise SystemExit(
                "numNodes slices differ (%s vs %s): this file holds more than one "
                "DAG, so converting a single slice would silently drop data."
                % (names[0], nn))
    if verbose:
        print("numNodes slices %s are identical (%d distinct dataflow records); "
              "converting slice numNodes=%s" % (names, len(base), names[0]), file=sys.stderr)
    return slices[names[0]]


def solve_sizes(rows):
    """Per-file size in MiB, with provenance for each file.

    A (task, operation) pair shares one `aggregateFilesizeMBtask`, so each pair
    is a constraint "sum of these files == this many MiB".  Single-file groups
    give a size outright; the rest are solved by elimination wherever a group
    has exactly one unknown left.
    """
    members = collections.defaultdict(set)
    for r in rows:
        members[(r["taskPID"], r["operation"])].add(r["fileName"])

    # One constraint per distinct file set, tagged with the operation that
    # produced it: a write group measures what was produced, a read group only
    # measures bytes moved (re-reads inflate it), so writes are preferred.
    constraints = {}
    for r in rows:
        group = frozenset(members[(r["taskPID"], r["operation"])])
        constraints.setdefault((group, r["operation"]),
                               float(r["aggregateFilesizeMBtask"]))

    size, prov, spread = {}, {}, {}
    for (group, op), total in constraints.items():
        if len(group) == 1 and op == "write":
            name = next(iter(group))
            size[name], prov[name] = total, "written"
    for (group, op), total in constraints.items():
        if len(group) == 1 and op == "read" and next(iter(group)) not in size:
            name = next(iter(group))
            size[name], prov[name] = total, "read-alone"

    while True:
        candidates = collections.defaultdict(list)
        for (group, _op), total in constraints.items():
            unknown = [f for f in group if f not in size]
            if len(unknown) == 1:
                candidates[unknown[0]].append(total - sum(size[f] for f in group
                                                          if f in size))
        if not candidates:
            break
        for name, estimates in candidates.items():
            # Over-determined and slightly inconsistent (read aggregates count
            # re-reads), so take the median and keep the spread on the record.
            size[name] = statistics.median(estimates)
            prov[name] = "derived"
            if len(estimates) > 1:
                lo, hi = min(estimates), max(estimates)
                spread[name] = {"estimates": len(estimates), "minMiB": lo, "maxMiB": hi,
                                "relativeSpread": (hi - lo) / hi if hi else 0.0}
    return size, prov, spread


def convert(rows, name, description, source, author, strict=False):
    io_rows = [r for r in rows if r["operation"] in IO_OPS and r["taskPID"]]
    other = [r for r in rows if r not in io_rows]

    size, prov, spread = solve_sizes(io_rows)

    task_id = lambda r: "%s_%s" % (r["taskName"], r["taskPID"])
    tasks = {task_id(r): r["taskName"] for r in io_rows}
    files = sorted({r["fileName"] for r in io_rows})

    inputs = collections.defaultdict(set)
    outputs = collections.defaultdict(set)
    for r in io_rows:
        (inputs if r["operation"] == "read" else outputs)[task_id(r)].add(r["fileName"])

    producers = collections.defaultdict(set)
    for t, outs in outputs.items():
        for f in outs:
            producers[f].add(t)
    parents = {t: set() for t in tasks}
    children = {t: set() for t in tasks}
    for t, ins in inputs.items():
        for f in ins:
            for p in producers.get(f, ()):
                if p != t:
                    parents[t].add(p)
                    children[p].add(t)

    spec_tasks = [
        {
            "name": tasks[t],
            "id": t,
            "parents": sorted(parents[t]),
            "children": sorted(children[t]),
            "inputFiles": sorted(inputs[t]),
            "outputFiles": sorted(outputs[t]),
        }
        for t in sorted(tasks)
    ]
    spec_files = [
        {"id": f, "sizeInBytes": int(round(size.get(f, 0.0) * MIB))} for f in files
    ]

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
        .isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "schemaVersion": SCHEMA_VERSION,
        "author": author,
        "workflow": {"specification": {"tasks": spec_tasks, "files": spec_files,
                                       "metrics": metrics}},
    }
    if strict:
        return instance

    dataflow = []
    for r in sorted(io_rows, key=lambda r: (task_id(r), r["fileName"], r["operation"])):
        dataflow.append({
            "task": task_id(r),
            "file": r["fileName"],
            "role": r["operation"],
            "transferSizeInBytes": float(r["transferSize"]),
            "opCount": int(r["opCount"]),
            "ioTimeInSeconds": float(r["totalTime"]),
            "throughputMiBps": float(r["trMiB"]),
            "storageType": r["storageType"],
        })
    per_task = {}
    for r in io_rows:
        e = per_task.setdefault(task_id(r), {})
        e["%sMiB" % r["operation"]] = float(r["aggregateFilesizeMBtask"])
        e["%sIoTimeInSeconds" % r["operation"]] = float(r["totalTime"])

    instance["elasticflow"] = {
        "sourceCsv": source,
        "numNodesSlice": rows[0]["numNodes"],
        "numNodesList": rows[0].get("numNodesList", ""),
        "scalingDimension": None,
        "scalingFactor": None,
        "notes": [
            "numNodes {2,5,10} does not vary the DAG; the slices are identical "
            "apart from placement and estimated_* columns, so this is a single "
            "measured run, not a scaling series.",
            "No WfFormat `execution` block: the CSV's `totalTime` is I/O "
            "transfer time (trMiB == aggregateFilesizeMBtask / totalTime), not "
            "task wall-clock runtime, so there is no runtimeInSeconds to report.",
            "`cp`/`scp`/`none` rows carry no taskPID (stage-in/stage-out data "
            "movement) and are counted in `excludedRows`, not made into tasks.",
        ],
        "fileSizeProvenance": {
            "written": sorted(f for f in files if prov.get(f) == "written"),
            "readAlone": sorted(f for f in files if prov.get(f) == "read-alone"),
            "derived": sorted(f for f in files if prov.get(f) == "derived"),
            "unknown": sorted(f for f in files if f not in prov),
        },
        "derivedSizeSpread": spread,
        "excludedRows": dict(collections.Counter(r["operation"] for r in other)),
        "taskIo": per_task,
        "dataflow": dataflow,
    }
    return instance


def self_check(rows, instance):
    """Verify the claims the module docstring makes about the source data."""
    problems = []
    io_rows = [r for r in rows if r["operation"] in IO_OPS and r["taskPID"]]

    bad = 0
    for r in io_rows:
        try:
            predicted = float(r["aggregateFilesizeMBtask"]) / float(r["totalTime"])
            if abs(predicted - float(r["trMiB"])) / max(float(r["trMiB"]), 1e-9) > 0.02:
                bad += 1
        except (ValueError, ZeroDivisionError):
            bad += 1
    if bad:
        problems.append("totalTime is not I/O time on %d/%d rows" % (bad, len(io_rows)))

    writers = collections.defaultdict(set)
    for r in io_rows:
        if r["operation"] == "write":
            writers[r["taskPID"]].add(r["fileName"])
    multi = [p for p, fs in writers.items() if len(fs) > 1]
    if multi:
        problems.append("%d tasks write >1 file, so written sizes are not exact"
                        % len(multi))

    for f in instance["workflow"]["specification"]["files"]:
        if not RE_FILE_ID.match(f["id"]):
            problems.append("file id violates the WfFormat pattern: %s" % f["id"])
    for t in instance["workflow"]["specification"]["tasks"]:
        if not RE_TASK_ID.match(t["id"]):
            problems.append("task id violates the WfFormat pattern: %s" % t["id"])
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="ElasticFlow *_workflow_data*.csv")
    ap.add_argument("-o", "--output", required=True, help="output JSON path")
    ap.add_argument("--name", default=None, help="WfFormat instance name")
    ap.add_argument("--strict", action="store_true",
                    help="emit standard WfFormat only; drop the `elasticflow` extension")
    ap.add_argument("--author-name", default=None)
    ap.add_argument("--author-email", default=None)
    ap.add_argument("--author-institution", default="Pacific Northwest National Laboratory")
    ap.add_argument("--author-country", default="US")
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

    rows = pick_slice(load(args.csv))
    name = args.name or "1000genome-elasticflow-%s" % re.sub(
        r"[^0-9a-zA-Z]+", "-", os.path.splitext(os.path.basename(args.csv))[0]).strip("-")
    description = (
        "1000 Genomes workflow run measured by ElasticFlow "
        "(github.com/PerfLab-EXaCT/ElasticFlow), converted to WfFormat from %s. "
        "File sizes are measured I/O in MiB converted to bytes; see the "
        "`elasticflow` key for per-file size provenance and the measured I/O "
        "that WfFormat has no field for." % args.csv)

    instance = convert(rows, name, description, args.csv, author, strict=args.strict)

    problems = check(instance) + self_check(rows, instance)
    if problems:
        for p in problems:
            print("FAIL  %s" % p, file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as fh:
        json.dump(instance, fh, indent=2)
        fh.write("\n")

    m = instance["workflow"]["specification"]["metrics"]
    print("ok  %s -> %s" % (args.csv, args.output))
    print("    %d tasks, %d files, %d levels, widths %d-%d, %.2f GiB total"
          % (m["numberOfTasks"], m["numberOfFiles"], m["numberOfLevels"],
             m["minimumWidth"], m["maximumWidth"],
             m["sumOfFileSizesInBytes"] / 1024 ** 3))
    if not args.strict:
        p = instance["elasticflow"]["fileSizeProvenance"]
        print("    file sizes: %d written, %d read-alone, %d derived, %d unknown"
              % (len(p["written"]), len(p["readAlone"]), len(p["derived"]),
                 len(p["unknown"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
