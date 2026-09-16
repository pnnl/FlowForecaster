"""
Generate traced workflow instances that obey a specified scaling behaviour.

Why this exists: validating rule inference needs a series whose correct answer is
known independently.  The original example set (now depreciated/sample_data)
cannot do that job for task scaling -- across its 1x/2x/3x task series the
fan-out degree moves only from 4.000 to 4.333, and the _task_scale_2.0 and
_task_scale_3.0 files are byte identical -- so nothing in it distinguishes a
working task-scaling model from a broken one.

What it produces is the 1000 Genomes topology in the traced GraphML format the
folding code consumes ("<prefix>_taskid<N>", "<base>_fileid<N><ext>", iterations
chained through dummy_task), at whatever scales are asked for, with dataflow
computed from an explicit per-edge exponent specification:

    V(edge) = V_base * data_scale ** p_V_data * task_scale ** p_V_task
    S(edge) = S_base * data_scale ** p_S_data * task_scale ** p_S_task

and fan-out degrees that actually grow with the task scale.  The expected rule
per edge is derived from the same exponents by the criteria the inference uses,
and written to a JSON sidecar, so validate_scaling_model.py can score a recovered
model without anyone restating the ground truth by hand.

Units are realistic: volumes in bytes around tens of MB, access size 4096.
"""

import argparse
import json
import os
import random

import networkx as nx

MB = 1024 * 1024

# Core edges of the 1000 Genomes workflow, with the behaviour each one is
# generated to obey.  Exponents are of the scale factor: 1 means proportional,
# 0 unchanged, -1 inversely proportional.
#
#   p_v_data / p_s_data   response of volume / access size to the data scale
#   p_v_task / p_s_task   response of volume / access size to the task scale
#
# Two named specifications, because "scaling the task count" has two physically
# reasonable meanings and they imply different rules:
#
#   split      A fixed input is divided among more consumers, so each consumer's
#              volume falls as 1/k.  Fan-outs become Rule 3.  The sequential
#              edge out of `individuals` also falls as 1/k, which none of the
#              seven analytical rules covers -- so that edge is expected to land
#              on Rule 8, deliberately.
#   replicate  Each task handles a fixed-size chunk, so more tasks means more
#              total work and each edge's volume is unchanged.  This reproduces
#              the assignment the paper's Table I/II reports for 1000 Genomes,
#              where Individuals is Rule 4 and every stage keeps S = 4096.
#
# Access size is a fixed 4096-byte block throughout, as the paper reports for
# this workflow, and the merge writes a fixed-size archive whatever its input.
SPLIT_SPEC = {
    "vcf->individuals":        dict(v=25 * MB, s=4096, p_v_data=1, p_s_data=0, p_v_task=-1, p_s_task=0),
    "individuals->chunk":      dict(v=12 * MB, s=4096, p_v_data=1, p_s_data=0, p_v_task=-1, p_s_task=0),
    "ann->sifting":            dict(v=8 * MB,  s=4096, p_v_data=1, p_s_data=0, p_v_task=0,  p_s_task=0),
    "sifting->sifted":         dict(v=2 * MB,  s=4096, p_v_data=1, p_s_data=0, p_v_task=0,  p_s_task=0),
    "chunk->merge":            dict(v=12 * MB, s=4096, p_v_data=1, p_s_data=0, p_v_task=-1, p_s_task=0),
    "merge->archive":          dict(v=40 * MB, s=4096, p_v_data=0, p_s_data=0, p_v_task=0,  p_s_task=0),
    "archive->mutation":       dict(v=20 * MB, s=4096, p_v_data=1, p_s_data=0, p_v_task=-1, p_s_task=0),
    "archive->frequency":      dict(v=20 * MB, s=4096, p_v_data=1, p_s_data=0, p_v_task=-1, p_s_task=0),
    "sifted->mutation":        dict(v=2 * MB,  s=4096, p_v_data=1, p_s_data=0, p_v_task=0,  p_s_task=0),
    "sifted->frequency":       dict(v=2 * MB,  s=4096, p_v_data=1, p_s_data=0, p_v_task=0,  p_s_task=0),
    "mutation->out":           dict(v=3 * MB,  s=4096, p_v_data=1, p_s_data=0, p_v_task=0,  p_s_task=0),
    "frequency->out":          dict(v=3 * MB,  s=4096, p_v_data=1, p_s_data=0, p_v_task=0,  p_s_task=0),
}

# Same volumes and access sizes; every task-scaling exponent is zero, so growing
# the task count grows the total work rather than subdividing fixed work.
REPLICATE_SPEC = {
    key: dict(entry, p_v_task=0, p_s_task=0) for key, entry in SPLIT_SPEC.items()
}

SPECS = {"split": SPLIT_SPEC, "replicate": REPLICATE_SPEC}

# Core-graph vertex name each spec edge folds to, so the sidecar can be keyed the
# way the canonical model is.
CORE_EDGE_NAME = {
    "vcf->individuals":   ("ALL.chr1.250000.vcf", "individuals", "fan-out"),
    "individuals->chunk": ("individuals", "chr1n-.tar.gz", "sequential"),
    "ann->sifting":       ("ALL.chr1.annotation.vcf", "sifting", "sequential"),
    "sifting->sifted":    ("sifting", "sifted.SIFT.chr1.txt", "sequential"),
    "chunk->merge":       ("chr1n-.tar.gz", "individuals_merge", "fan-in"),
    "merge->archive":     ("individuals_merge", "chr1n.tar.gz", "sequential"),
    "archive->mutation":  ("chr1n.tar.gz", "mutation_overlap", "fan-out"),
    "archive->frequency": ("chr1n.tar.gz", "frequency", "fan-out"),
    "sifted->mutation":   ("sifted.SIFT.chr1.txt", "mutation_overlap", "fan-out"),
    "sifted->frequency":  ("sifted.SIFT.chr1.txt", "frequency", "fan-out"),
    "mutation->out":      ("mutation_overlap", "chr1-.txt.tar.gz", "sequential"),
    "frequency->out":     ("frequency", "chr1-.txt-freq.tar.gz", "sequential"),
}


class Namer:
    """Hands out the traced instance's "<prefix>_taskid<N>" names."""

    def __init__(self):
        self.counters = {}

    def task(self, prefix):
        index = self.counters.get(prefix, 0)
        self.counters[prefix] = index + 1
        return f"{prefix}_taskid{index}"


def value(spec_key, spec, data_scale, task_scale, jitter, rng):
    """Volume and access size of one edge at the requested scales."""
    entry = spec[spec_key]
    volume = entry["v"] * (data_scale ** entry["p_v_data"]) * (task_scale ** entry["p_v_task"])
    size = entry["s"] * (data_scale ** entry["p_s_data"]) * (task_scale ** entry["p_s_task"])
    if jitter:
        volume *= 1.0 + rng.uniform(-jitter, jitter)
        size *= 1.0 + rng.uniform(-jitter, jitter)
    # Traced instances declare these as integers; the bases are large enough
    # that rounding stays far below any matching threshold.
    return max(1, int(round(volume))), max(1, int(round(size)))


def build_instance(threads: int, iterations: int, data_scale: float, task_scale: float,
                   spec: dict, base_individuals: int, base_outputs: int,
                   jitter: float, seed: int) -> nx.DiGraph:
    """
    Emit one traced instance.

    Task scaling multiplies the fan-out degrees -- the number of `individuals`
    tasks and the number of `mutation_overlap` / `frequency` tasks -- because
    that is what scaling the task count means.  A series where those stay put
    cannot exercise structural projection.
    """
    rng = random.Random(seed)
    G = nx.DiGraph()
    namer = Namer()

    n_individuals = max(1, int(round(base_individuals * task_scale)))
    n_outputs = max(1, int(round(base_outputs * task_scale)))

    def add_file(name, size):
        G.add_node(name, type="file", size=max(1, int(round(size))))
        return name

    def add_task(prefix):
        name = namer.task(prefix)
        G.add_node(name, type="task")
        return name

    def link(src, dst, spec_key):
        volume, access = value(spec_key, spec, data_scale, task_scale, jitter, rng)
        G.add_edge(src, dst, data_volume=volume, access_size=access)

    for thread in range(threads):
        # fileid is unique per (thread, iteration): thread 0 gets 0..I-1, etc.
        previous_outputs = None
        for iteration in range(iterations):
            fid = thread * iterations + iteration

            vcf = f"ALL.chr1.250000_fileid{fid}.vcf"
            ann = f"ALL.chr1.annotation_fileid{fid}.vcf"
            add_file(vcf, 25 * MB * data_scale)
            add_file(ann, 8 * MB * data_scale)

            if previous_outputs is not None:
                # dummy_task closes an iteration and produces the next one's
                # inputs; this is the chaining the time fold collapses.
                dummy = add_task("dummy_task")
                for out_file in previous_outputs:
                    link(out_file, dummy, "mutation->out")
                link(dummy, vcf, "mutation->out")
                link(dummy, ann, "mutation->out")

            # Individuals: one fan-out from the VCF per chunk.
            chunks = []
            for i in range(n_individuals):
                task = add_task("individuals")
                link(vcf, task, "vcf->individuals")
                chunk = add_file(f"chr1n-{i}.tar_fileid{fid}.gz", 12 * MB * data_scale / n_individuals)
                link(task, chunk, "individuals->chunk")
                chunks.append(chunk)

            # Sifting is a single sequential stage.
            sifting = add_task("sifting")
            link(ann, sifting, "ann->sifting")
            sifted = add_file(f"sifted.SIFT.chr1_fileid{fid}.txt", 2 * MB * data_scale)
            link(sifting, sifted, "sifting->sifted")

            # Merge: fan-in over every chunk, writing a fixed-size archive.
            merge = add_task("individuals_merge")
            for chunk in chunks:
                link(chunk, merge, "chunk->merge")
            archive = add_file(f"chr1n.tar_fileid{fid}.gz", 40 * MB)
            link(merge, archive, "merge->archive")

            # Mutation overlap and frequency both fan out from the archive and
            # the sifted list.
            outputs = []
            for i in range(n_outputs):
                mutation = add_task("mutation_overlap")
                link(archive, mutation, "archive->mutation")
                link(sifted, mutation, "sifted->mutation")
                m_out = add_file(f"chr1-{i}.txt.tar_fileid{fid}.gz", 3 * MB * data_scale)
                link(mutation, m_out, "mutation->out")
                outputs.append(m_out)

                frequency = add_task("frequency")
                link(archive, frequency, "archive->frequency")
                link(sifted, frequency, "sifted->frequency")
                f_out = add_file(f"chr1-{i}.txt-freq.tar_fileid{fid}.gz", 3 * MB * data_scale)
                link(frequency, f_out, "frequency->out")
                outputs.append(f_out)

            previous_outputs = outputs

    G.graph["synthetic"] = True
    return G


def expected_rules(spec_key: str, dimension: str, spec: dict, tolerance: float = 0.10):
    """
    The rule(s) the inference may legitimately recover for one edge.

    Derived from the same exponents the dataflow was generated from, by the
    criteria the matcher applies, so the ground truth and the thing under test
    are stated in the same language rather than asserted independently.

    A list, not a single id, because the rule set is not injective.  Under task
    scaling Rule 4 and Rule 7 make the identical prediction -- A' = A, S' = S,
    V' = V -- so an edge whose every metric is flat satisfies both, and scoring
    it against one arbitrarily chosen id would fail a correct model on a coin
    flip.  The first entry is the most specific match; any entry counts as
    correct.
    """
    entry = spec[spec_key]
    _, _, edge_type = CORE_EDGE_NAME[spec_key]
    p_v = entry["p_v_data"] if dimension == "data" else entry["p_v_task"]
    p_s = entry["p_s_data"] if dimension == "data" else entry["p_s_task"]

    def near(value, target):
        return abs(value - target) <= tolerance

    flat = near(p_v, 0) and near(p_s, 0)

    if dimension == "data":
        if flat:
            # Rule 4 is the named "fixed input data" case; Rule 7's data branch
            # states V' = kV, so it does not also apply here.
            return [4]
        if edge_type == "fan-out":
            return [1] if (near(p_v, 1) and near(p_s, 0)) else [2]
        if edge_type == "fan-in":
            # The aggregate is num_sources * V and num_sources is fixed under
            # data scaling, so the aggregate follows V.
            return [5] if near(p_v, 1) else [6]
        return [7] if near(p_v, 1) else [8]

    # Task scaling.  Rules 4 and 7 coincide on a flat edge whatever its fan
    # pattern, so both are acceptable there.
    if flat:
        if edge_type == "fan-in":
            # num_sources grows with k, so a flat per-edge volume means the
            # aggregate grows with k: that is Rule 5's VSigma' = k VSigma.
            return [5, 4, 7]
        return [4, 7]
    if edge_type == "fan-out":
        if near(p_v, -1):
            return [3]
    if edge_type == "fan-in":
        # The aggregate exponent is p_v + 1: proportional is Rule 5, fixed is
        # Rule 6.
        if near(p_v + 1, 1):
            return [5]
        if near(p_v + 1, 0):
            return [6]
    # No analytical rule states this response; the empirical fallback is the
    # correct answer, not a failure.
    return [8]


# Older name, kept for callers that want just the primary expectation.
def expected_rule(spec_key: str, dimension: str, spec: dict, tolerance: float = 0.10) -> int:
    return expected_rules(spec_key, dimension, spec, tolerance)[0]


def main():
    parser = argparse.ArgumentParser(
        description="Generate traced 1000 Genomes instances that obey a specified scaling behaviour",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--outdir", default="synthetic_data/1000Genomes",
                        help="directory for the generated GraphML")
    parser.add_argument("--prefix", default="synth.1k_genome",
                        help="filename stem for the generated instances")
    parser.add_argument("--data-scales", nargs='+', type=float, default=[1.0, 2.0, 4.0, 8.0],
                        help="data scales to emit (default: the paper's 1/2/4/8 series)")
    parser.add_argument("--task-scales", nargs='+', type=float, default=[1.0, 2.0, 4.0, 8.0],
                        help="task scales to emit")
    parser.add_argument("--threads", type=int, default=2, help="parallel pipelines per instance")
    parser.add_argument("--iterations", type=int, default=3, help="loop iterations per thread")
    parser.add_argument("--individuals", type=int, default=4,
                        help="individuals tasks at task scale 1 (grows with the task scale)")
    parser.add_argument("--outputs", type=int, default=2,
                        help="mutation_overlap/frequency tasks at task scale 1")
    parser.add_argument("--jitter", type=float, default=0.0,
                        help="relative noise per measurement (default 0: exact, so rule "
                             "recovery is deterministic). 0.05 gives realistic spread.")
    parser.add_argument("--seed", type=int, default=20260916, help="RNG seed for --jitter")
    parser.add_argument("--tolerance", type=float, default=0.10,
                        help="threshold used to derive the expected rule per edge")
    parser.add_argument("--spec", choices=sorted(SPECS), default="replicate",
                        help="what task scaling means: 'replicate' (more tasks, more "
                             "total work -- reproduces the paper's Table I/II rule "
                             "assignment for 1000 Genomes) or 'split' (a fixed input "
                             "divided among more consumers)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    spec = SPECS[args.spec]
    manifest = {"generator": "make_synthetic_instances.py", "spec_name": args.spec,
                "threads": args.threads, "iterations": args.iterations,
                "base_individuals": args.individuals, "base_outputs": args.outputs,
                "jitter": args.jitter, "tolerance": args.tolerance,
                "spec": spec, "series": {}, "expected_rules": {}}

    for dimension, scales in (("data", args.data_scales), ("task", args.task_scales)):
        emitted = []
        for scale in scales:
            data_scale = scale if dimension == "data" else 1.0
            task_scale = scale if dimension == "task" else 1.0
            G = build_instance(args.threads, args.iterations, data_scale, task_scale, spec,
                               args.individuals, args.outputs, args.jitter, args.seed)
            suffix = "" if scale == 1.0 else f"_{dimension}_scale_{scale}"
            path = os.path.join(
                args.outdir,
                f"{args.prefix}.iter-{args.iterations}.thrd-{args.threads}{suffix}.graphml")
            nx.write_graphml(G, path)
            # Record the bare filename, not the path we happened to write to.  The
            # manifest sits beside the instances it describes, so the directory adds
            # nothing -- and baking --outdir into it made the file differ on every
            # regeneration into a different directory, which reads as nondeterminism
            # in data whose whole purpose is to be a reproducible fixture.
            emitted.append({"file": os.path.basename(path), "scale": scale,
                            "nodes": G.number_of_nodes(), "edges": G.number_of_edges()})
            print(f"{dimension:>4} {scale:>5.2f}x  {path}  "
                  f"({G.number_of_nodes()} vertices, {G.number_of_edges()} edges)")

        manifest["series"][dimension] = emitted
        manifest["expected_rules"][dimension] = {
            "%s -> %s" % CORE_EDGE_NAME[key][:2]: expected_rules(key, dimension, spec, args.tolerance)
            for key in spec
        }

    manifest_path = os.path.join(args.outdir, "ground_truth.json")
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"\nGround truth -> {manifest_path}")
    for dimension in ("data", "task"):
        print(f"\n  expected {dimension} scaling rules:")
        for edge, rule_ids in sorted(manifest["expected_rules"][dimension].items()):
            accepted = " or ".join(f"Rule {r}" for r in rule_ids)
            print(f"    {accepted:<24} {edge}")


if __name__ == "__main__":
    main()
