# FlowForecaster

Infers interpretable scaling models from a handful of traced workflow instances,
then uses them to forecast a workflow's dataflow and DAG structure at a scale that
was never run.

## Install

```bash
pip install -r requirements.txt
```

Or directly:

```bash
pip install numpy networkx matplotlib pandas
```

All commands below run from the repository root. (They also work from `src/`; the
scripts resolve `utils/` from their own location rather than from the working
directory.)

## Test data

The repo ships a 1000 Genomes series in `synthetic_data/1000Genomes/`, traced at
1x, 2x, 4x and 8x in both scaling dimensions, plus a `ground_truth.json` recording
the rule each core edge should be assigned. The examples below use it, so they can
be run as written and the output checked against a known answer.

The commands use this shorthand for brevity:

```bash
D=synthetic_data/1000Genomes
```

Its 1x instance is topologically identical to the original example instance (136
vertices, 186 edges, 23 levels). What it adds is a task series that genuinely
expands the DAG — 136 → 232 → 424 → 808 vertices — which is what makes a
task-scaling model testable. See [Regenerating and extending the test
data](#5-regenerating-and-extending-the-test-data) and
[`depreciated/sample_data/README.md`](depreciated/sample_data/README.md).

## 1. Infer the scaling models

You need at least two traced instances per scaling dimension — three or more if
you want the fit residual to mean anything. Give the scale each instance was
traced at with `--data-scales` / `--task-scales`, in the same order as the files.
Either dimension on its own is fine; give both only if you traced both:

```bash
python3 src/create_canonical_model_auto_scaling.py \
  --data-instances $D/synth.1k_genome.iter-3.thrd-2.graphml \
                   $D/synth.1k_genome.iter-3.thrd-2_data_scale_2.0.graphml \
                   $D/synth.1k_genome.iter-3.thrd-2_data_scale_4.0.graphml \
                   $D/synth.1k_genome.iter-3.thrd-2_data_scale_8.0.graphml \
  --data-scales 1 2 4 8 \
  --task-instances $D/synth.1k_genome.iter-3.thrd-2.graphml \
                   $D/synth.1k_genome.iter-3.thrd-2_task_scale_2.0.graphml \
                   $D/synth.1k_genome.iter-3.thrd-2_task_scale_4.0.graphml \
                   $D/synth.1k_genome.iter-3.thrd-2_task_scale_8.0.graphml \
  --task-scales 1 2 4 8 \
  --output-data models/canonical_1000genomes_data.graphml \
  --output-task models/canonical_1000genomes_task.graphml
```

The scales matter. Without them the series is assumed to be 1x, 2x, 3x, …, so this
2x/4x/8x series would be fitted as though it were 1/2/3 and no analytical rule
would match it. Output directories are created if they do not exist.

Useful flags:

| Flag | Meaning |
| --- | --- |
| `--tolerance P` | matching threshold, default `0.10`. The paper notes that at 1% almost everything falls through to Rule 8. |
| `--defer-on TASK` | mark a stage whose input sizes are genuinely unknown until a predecessor runs (§III-F). Repeatable. Its rules are evaluated lazily. |
| `--auto-defer` | defer every edge whose within-instance spread exceeds the threshold. Blunt: ordinary loop-to-loop variance trips it, so prefer `--defer-on`. |
| `--model-in-data`, `--model-in-task` | reuse a saved model instead of re-inferring, e.g. to project at a new scale. |

The run prints, per edge, the measured series, the classified response, the rule
chosen and a confidence derived from the fit residual — so a model can be read and
argued with, not just used.

## 2. Forecast at a target scale

Either as part of the run above:

```bash
python3 src/create_canonical_model_auto_scaling.py ... \
  --project --project-data-scale 16 --project-task-scale 16 \
  --project-output-dir projections \
  --project-threads 2 --project-iterations 3
```

or from a saved model:

```bash
python3 src/project_at_scale.py \
  --model models/canonical_1000genomes_task.graphml \
  --scale 16 --dimension task \
  --core-output projections/core_16x.graphml \
  --output projections/dag_16x.graphml \
  --threads 2 --iterations 3
```

This emits two graphs. The one named by `--core-output` is the folded model with
every metric predicted at the target scale — one vertex per workflow stage,
convenient for comparing against a measured instance edge by edge. The one named
by `--output` is the unfolded DAG: the core graph expanded back out using the
predicted fan multiplicities, so a task-scaling forecast actually contains the new
tasks it predicts. `--threads` and `--iterations` set how many pipeline copies and
loop iterations to emit; match them to the traced instances (these are
`iter-3.thrd-2`, so 2 threads and 3 iterations) if you want to compare directly.

## 3. Convert to WfFormat

For a traced instance:

```bash
python3 src/graphml_to_wfformat.py $D/*.graphml \
  --outdir wfinstances/1000genomes --name-prefix 1000genome-flowforecaster
```

Output is grouped under `--outdir` by the top-level directory the inputs came
from, so that lands in `wfinstances/1000genomes/synthetic_data/`. The converted
instances are not committed -- they are reproducible from the GraphML that is, and
`wfinstances/` is a build product, not a source.

`--name-prefix` sets the WfFormat `name` field and defaults to
`1000genome-flowforecaster`, so pass your own when converting anything else.

For a forecast, which is labelled as predicted rather than measured:

```bash
python3 src/graphml_to_wfformat.py \
  --from-projection projections/dag_16x.graphml \
  --projection-model models/canonical_1000genomes_task.graphml \
  --outdir wfinstances/projections
```

The projected JSON carries a `flowforecaster.provenance` of `projected`, a
`warnings` entry stating plainly that nothing in it was traced, and a `projection`
block recording the model, the target scale and the rule histogram behind it.
Authorship comes from your git config; override with `--author-name` and
`--author-email`.

Note that FlowForecaster property graphs carry abstract, unitless data quantities,
not measured bytes; `sizeInBytes`, `dataVolume` and `accessSize` reproduce the
GraphML values verbatim so that ratios across a series stay exact.

## 4. Validate a model

Fit on some scales, predict the ones withheld, and score the result against what
was actually traced there:

```bash
python3 src/validate_scaling_model.py \
  --instances $D/synth.1k_genome.iter-3.thrd-2.graphml \
              $D/synth.1k_genome.iter-3.thrd-2_task_scale_2.0.graphml \
              $D/synth.1k_genome.iter-3.thrd-2_task_scale_4.0.graphml \
              $D/synth.1k_genome.iter-3.thrd-2_task_scale_8.0.graphml \
  --scales 1 2 4 8 --dimension task --train 1 2 4 --test 8 \
  --ground-truth $D/ground_truth.json \
  --check-projection
```

Swap `--dimension task` for `--dimension data` and the `_task_scale_` filenames for
`_data_scale_` to validate the other dimension.

Three things are scored. Per-edge **prediction accuracy** at each held-out scale.
**Rule recovery** against `ground_truth.json` — which accepts a *list* of rule ids
per edge, because the rule set is not injective: under task scaling Rules 4 and 7
make the identical prediction, so demanding one arbitrarily chosen id would fail a
correct model on a coin flip. And, with `--check-projection`, the **projected DAG's
shape** — task count per stage, file count, edge count — against the instance
traced at that scale. Without that last one the unfolder goes untested, and under
task scaling the whole claim is that new tasks are predicted: a model can get every
per-edge volume right while emitting the wrong number of tasks.

The `dummy_task` scaffold is excluded from both sides of the structure comparison
and the exclusion is printed. Folding absorbs it into the iteration count, so the
core model has no vertex for it and the unfolder re-expresses it as `--iterations`
copies of the pipeline. Pass `--scaffold-task ''` to compare it too.

Accuracy is only reported on held-out scales; a power law through its own training
points always looks good, which is why the fit residual is folded into each rule's
confidence instead. The script exits non-zero on any miss, so it works as a
regression gate.

## 5. Regenerating and extending the test data

`synthetic_data/` is committed, so you do not need this to run anything above. Use
it to regenerate the series, change its shape, or generate a different scaling
behaviour. The generator writes the 1000 Genomes topology in the traced GraphML
format at whatever scales you ask for, with dataflow computed from an explicit
per-edge exponent specification, plus the `ground_truth.json` that
`--check-projection` and `--ground-truth` score against:

```bash
python3 src/make_synthetic_instances.py \
  --outdir synthetic_data/1000Genomes \
  --data-scales 1 2 4 8 --task-scales 1 2 4 8
```

That is the exact command that produced the committed data; the seed is fixed, so
it reproduces byte-identically.

- `--spec replicate` (the default) means more tasks do more total work. This
  reproduces the rule assignment the paper's Table I/II reports for 1000 Genomes:
  Individuals → Rule 4, Merge → Rule 5, Sifting/Frequency/Mutation → Rule 7.
- `--spec split` means a fixed input is divided among more consumers, which
  exercises Rule 3 and includes one edge only the Rule 8 empirical fallback can
  describe. Not committed — generate it into a scratch directory when you want to
  cover those rules.
- `--jitter 0.05` adds per-measurement noise. The default of 0 keeps rule recovery
  deterministic; rule recovery survives 10% jitter in both dimensions.
- `--threads`, `--iterations`, `--individuals`, `--outputs`, `--seed`,
  `--tolerance` control the fold shape, the fan-out widths and the fit threshold.

## Input format

Traced instances are GraphML with four attributes — node `type` (`task` or `file`)
and `size`, edge `data_volume` and `access_size`. Access count is not recorded and
is derived as A = V / S.

Names carry structure the folding step relies on: tasks are `<prefix>_taskid<N>`,
files are `<basename>_fileid<N><ext>`, each thread starts from its own root files,
and `dummy_task` terminates an iteration and produces the next one's inputs.

## The original example data

The five instances that used to sit in `sample_data/` are now under
[`depreciated/sample_data/`](depreciated/sample_data/README.md). They are kept
because the published results were produced from them and because they remain a
regression fixture, but they cannot test task scaling: across their 1x/2x/3x task
series the fan-out degree moves only from 4.000 to 4.333, and the
`_task_scale_2.0` and `_task_scale_3.0` files are byte-identical. Their
data-scaling series is sound.
