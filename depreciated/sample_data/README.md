# sample_data (set aside)

These five GraphML instances are the original shipped example data. They are kept
because the published results were produced from them, and because they remain a
useful regression fixture.  They are also the source the WfFormat instances under
`wfinstances/1000genomes/sample_data/` were converted from, and reproduce from
these files exactly apart from their `createdAt` timestamp.  To regenerate them
where they sit, now that this tree has moved:

    python3 src/graphml_to_wfformat.py depreciated/sample_data/1000Genomes/*.graphml \
      --flat --outdir wfinstances/1000genomes/sample_data

They were moved out of the main tree because they cannot serve as test data for
task scaling, which is what the run instructions now use `synthetic_data/` for:

- Across the 1x/2x/3x task series the fan-out degree moves only from 4.000 to
  4.333, so nothing in the series distinguishes a working task-scaling model from
  a broken one.
- `sample.1k_genome.iter-3.thrd-2_task_scale_2.0.graphml` and
  `..._task_scale_3.0.graphml` are byte-identical to each other.

The data-scaling series is fine, and inference over it still gives a sensible
model (Rules 1, 2, 4, 5 and 7, all twelve core edges matched analytically).

`synthetic_data/`, written by `src/make_synthetic_instances.py`, replaces these
for testing: its 1x instance is topologically identical to
`sample.1k_genome.iter-3.thrd-2.graphml` (136 vertices, 186 edges, 23 levels), but
its task series genuinely expands the DAG (136 -> 232 -> 424 -> 808 vertices) and
it ships a `ground_truth.json` recording the rule each edge should be assigned, so
rule recovery can be scored rather than eyeballed.
