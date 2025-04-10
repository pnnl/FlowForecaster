# FlowForecaster

## Install Dependent Python3 Library
```bash
$ pip install numpy networkx matplotlib pandas
```

## Run Time Folding Example

1. Synthesize a workflow of 3 iterations.
```shell
$ cd py1_flowforecaster
$ python py1.synthesize_graphml_iterations.1k_genome.v0.py data/dummy.1k_genome.graphml -i 3
```
Here `data/dummy.1k_genome.graphml` is a simplified 1000Genome workflow. `-i 3` means 3 iterations.
This will generate `dummy.1k_genome.iter-3.graphml` which contains 3 iterations based on the input workflow.

2. Show the generated workflow.
```shell
$ python py0.print_graphml.v1.py dummy.1k_genome.iter-3.graphml  
```
This will generate `dummy.1k_genome.iter-3.png`.

3. Create a compound graph by time-folding.
```shell
$ python py2.create_compound_graph.v0.py dummy.1k_genome.iter-3.graphml  
```
This will save the compound graph to `dummy.1k_genome.iter-3.statistic.graphml`.