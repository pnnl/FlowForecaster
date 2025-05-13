# FlowForecaster

## Install Dependent Python3 Library
```bash
$ pip install numpy networkx matplotlib pandas sortedcontainers
```

## Run Example of Space Folding and Time Folding

1. Synthesize a workflow of 3 iterations and 2 threads.
```shell
$ cd py1_flowforecaster
$ python py1.synthesize_graphml_iterations.1k_genome.v1.threads.py data/dummy.1k_genome.graphml -i 3 -t 2
```
Here `data/dummy.1k_genome.graphml` is a simplified 1000Genome workflow. 
`-i 3` means 3 iterations, and `-t 2` means 2 threads (independent parallel workflows).
This will generate `dummy.1k_genome.iter-3.thrd-2.graphml` which contains 3 iterations and 2 threads based on the input workflow.

2. Show the generated workflow.
```shell
$ python py0.print_graphml.v1.py dummy.1k_genome.iter-3.thrd-2.graphml  
```
This will generate image `dummy.1k_genome.iter-3.thrd-2.png`.

3. Create a compound graph by space-folding and time-folding.
```shell
$ python py3.do_space_time_folding.v0.py dummy.1k_genome.iter-3.thrd-2.graphml  
```
This will save the compound graph to `dummy.1k_genome.iter-3.thrd-2.statistic.graphml`.
The collected statistics are saved as a list of lists in each edge and vertex. Each inner list comes from  its thread. 
For example, `[[6.0, 3.5, 4.5], [6.0, 5.5, 6.5]]`, here `[6.0, 3.5, 4.5]` is from the first thread, 
and `[6.0, 5.5, 6.5]` is from the second thread.