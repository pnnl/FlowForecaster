
Examples
===============================================================================

Here is a set of example runs demonstrating how to start a flow forecaster, monitor its progress, collect results, and measure prediction accuracy. To execute a step, we have prepared an example run that includes 02 and 04 scaling `tasks` within the 1000 Genomes workflow. (Prepare a set of runs that follow the same execution process as described above.)


Initial Run (1000genome-workflow/02/run.sh)
-------------------------------------------------------------------------------

The script is designed to run on a specific example using the 1000 Genomes workflow. Our execution is intended to achieve twice the scaling of `tasks` compared to the other case. First, the script is ready to run:

  $ 1000genome-workflow/02/run.sh

    ...
    
PATTERN: *.fasta.amb PATHNAME: /qfs/projects/oddite/leeh736/git/1000genome-workflow/bin/<frozen importlib._bootstrap_external>
PATTERN: *.fasta.sa PATHNAME: /qfs/projects/oddite/leeh736/git/1000genome-workflow/bin/<frozen importlib._bootstrap_external>
PATTERN: *.fasta.bwt PATHNAME: /qfs/projects/oddite/leeh736/git/1000genome-workflow/bin/<frozen importlib._bootstrap_external>
PATTERN: *.fasta.pac PATHNAME: /qfs/projects/oddite/leeh736/git/1000genome-workflow/bin/<frozen importlib._bootstrap_external>
PATTERN: *.fasta.ann PATHNAME: /qfs/projects/oddite/leeh736/git/1000genome-workflow/bin/<frozen importlib._bootstrap_external>
PATTERN: *.fasta PATHNAME: /qfs/projects/oddite/leeh736/git/1000genome-workflow/bin/<frozen importlib._bootstrap_external>
Checkmeta calling open on file /qfs/projects/oddite/leeh736/git/1000genome-workflow/bin/<frozen importlib._bootstrap_external>
    ...


(Don't forget to run the script in 04 case as well)


Parse Flow Forecaster
-------------------------------------------------------------------------------

Once the main script is complete, Flow Forecaster is ready to process in a given setup. The statistics from actual executions may be scattered, but it is important to consolidate them in one place for later processing.

  $ cd 1000genome-workflow; python parse_dfls.py

    ... 
    chr1n-1-1251.tar.gz individuals_ID0000001 {'volume': 0, 'count': 0, 'size': 0}
    chr1n-1-1251.tar.gz individuals_merge_ID0000003 {'volume': 12815324, 'count': 92
    , 'size': 139297.0}
    [('chr1n-1-1251.tar.gz', 'individuals_merge', {'count': [92], 'edge_count': 1})]
    individuals_ID0000001 chr1n-1-1251.tar.gz {'volume': 5014692, 'count': 36, 'size
    ': 139297.0}
    [('chr1n-1-1251.tar.gz', 'individuals_merge', {'count': [92], 'edge_count': 1}),
     ('individuals', 'chr1n-1-1251.tar.gz', {'count': [36], 'edge_count': 1})]
    individuals_ID0000001 columns.txt {'volume': 0, 'count': 0, 'size': 0}
    individuals_ID0000001 ALL.chr1.2500.vcf {'volume': 0, 'count': 0, 'size': 0}
    individuals_merge_ID0000003 chr1n.tar.gz {'volume': 23699291, 'count': 77, 'size
    ': 307783.0}
    [('chr1n-1-1251.tar.gz', 'individuals_merge', {'count': [92], 'edge_count': 1}),
     ('individuals_merge', 'chr1n.tar.gz', {'count': [77], 'edge_count': 1}), ('indi
    viduals', 'chr1n-1-1251.tar.gz', {'count': [36], 'edge_count': 1})]
    ze': 0}
    columns.txt individuals_ID0000001 {'volume': 72924, 'count': 10, 'size': 7442.33
    3333333333}
    ...



Predict Flow Forecaster
-------------------------------------------------------------------------------

It's time to measure scaling accuracy of Flow Forecaster and evaluate how well the data has been collected within the given performance sets. For example, we try to run a four-task scaling compound graph toward a two-scaling graph:

   $  python predict_dfls.py --compound_graph count_04_task_scaling_compound_graph.edgelist --test_graph count_02_task_scaling_compound_graph.edgelist --factor 1

    columns.txt individuals {'accuracy': [100.0]}
    columns.txt frequency {'accuracy': [100.0]}
    ALL.chr1.2500.vcf individuals {'accuracy': [100.0]}
    chr1n.tar.gz frequency {'accuracy': [100.0]}
    sifted.SIFT.chr1.txt frequency {'accuracy': [100.0]} 


Expected Results
-------------------------------------------------------------------------------

As you can see, with 1000 Genomes workflow example, we achieve high scaling accuracy results. We can experiment with larger numbers and different metrics (e.g., volumes) to assess their impact on overall performance.

