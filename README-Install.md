<!-- -*-Mode: markdown;-*- -->
<!-- $Id: bd5988fb659f47215d89334363ba2b7ac2fe2b8f $ -->


Prerequisites
=============================================================================

Environment
  - CMake (>= version 2.8)
  - C++14 compiler, GCC preferred
  - Python 3.7+



Building & Installing
=============================================================================

....

1. Installing...
   ```sh
   mkdir <build> && cd <build>
   cmake \
     -DCMAKE_INSTALL_PREFIX=<install-path> \
     <datalife-root-path>
   make install
   ```


Using
=============================================================================

1. First use [DataLife](https://github.com/pnnl/DataLife) to monitor a
   few (e.g., 3--5) Data Flow Lifecycle profiles. The inputs should
   vary either input data sizes or parallelism. A Data Flow Lifecycle
   is a property DAGs with detailed data flow statistics.

   ```sh
    ...
    ...datalife
    ```


2. Model with FlowForecaster. This step will infer a detailed and
   interpretable workflow scaling model from a few empirical Data Flow
   Lifecycle property graphs.

   ```sh
    ...
    usage: datalife-analyze [-h] [-i INPUT] [-o OUTPUT]

    ....

    optional arguments:
      -h, --help            show this help message and exit
      -i INPUT, --input INPUT
                            read I/O monitor stats from directory path
      -o OUTPUT, --output OUTPUT
                            write a graph output to a file
    ```

3. Examine the model output. 
  
  ...
  
  A FlowForecaster model is an abstract directed acyclic graph (DAG)
  with analytical expressions to describe how the DAG scales and how
  data flows along edges. Importantly, FlowForecaster's expression
  language and rules can explain data dependent structure and
  flow. FlowForecaster's inference finds repeated substructure, infers
  analytical rules to explain substructure scaling (edge branching and
  joining), and predicts edge properties such as data accesses, access
  size, and data volume.


4. Predict the Data Flow Lifecycle graph using different values for
   the data size or task concurrency. Use the predictions for better
   scheduling.

