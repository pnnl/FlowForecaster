# FlowForecaster

## Install Dependent Python3 Library
```bash
$ pip install numpy networkx matplotlib pandas sortedcontainers
```

## Usage
```
bash
$ $ python create_canonical_model_auto_scaling.py \
  --data-instances <data_scaling_files> \
  --task-instances <task_scaling_files> \
  --output-data <data_model_output> \
  --output-task <task_model_output>
```

An example:

```bash
$ python src/create_canonical_model_auto_scaling.py --data-instances ../sample_data/1000Genomes/sample.1k_genome.iter-3.thrd-2.graphml ../sample_data/1000Genomes/sample.1k_genome.iter-3.thrd-2_data_scale_2.0.graphml  ../sample_data/1000Genomes/sample.1k_genome.iter-3.thrd-2_data_scale_3.0.graphml --task-instances ../sample_data/1000Genomes/sample.1k_genome.iter-3.thrd-2.graphml ../sample_data/1000Genomes/sample.1k_genome.iter-3.thrd-2_task_scale_2.0.graphml ../sample_data/1000Genomes/sample.1k_genome.iter-3.thrd-2_task_scale_3.0.graphml  --output-data canonical_1000genomes_data_scaling.graphml --output-task canonical_1000genomes_task_scaling.graphml
```