<!-- -*-Mode: markdown;-*- -->
<!-- $Id: 4098d4ffce45696ec3497ad9e08e712906c9d8fe $ -->


FlowForecaster
=============================================================================

**Home**:
  - https://github.com/pnnl/FlowForecaster
  
  - [Performance Lab for EXtreme Computing and daTa](https://github.com/perflab-exact)

  - Related: 
  [DataLife](https://github.com/pnnl/DataLife)
  [FlowForecaster](https://github.com/pnnl/FlowForecaster)
  <!-- [DaYu](https://github.com/pnnl/DaYu) -->
   

**About (Summary)**: To enable high quality scheduling decisions,
FlowForecaster automatically inferrs detailed and interpretable
scaling models for a large class of important distributed scientific
workflows from only a few empirical directed acyclic property graphs
(3--5).


**About**: 

Distributed scientific workflows underpin many areas of scientific
exploration. High quality scheduling decisions depend upon detailed
performance, available only at runtime, about data and data flows. If
it were possible to know such information ahead of time, schedulers
could make good decisions about resource allocation and scheduling.

To avoid laborious and manual profiling and introspection, we
introduce FlowForecaster, an efficient method for automatically
inferring detailed and interpretable workflow scaling models from only
a few (3--5) empirical task property graphs. A model represents
workflow control and data flow as an abstract DAG with analytical
expressions to describe how the DAG scales and how data flows along
edges. Thus, with a model and proposed workflow input, FlowForecaster
predicts the workflow's tasks, control, and data flow properties.  We
validate FlowForecaster on several workflows and find that we can
explain 97.3% of observed results on task and data scaling.

Our method is based on the fact that most workflows, following the
80-20% rule, execute in predictable patterns relative to concurrency
and input data sizes. We define a canonical models, formulate an
expression language, and develop an algorithm to infer detailed and
interpretable canonical scaling models from only a few (3--5)
empirical directed acyclic property graphs (DAG). The expression
language and rules that can explain data dependent structure and
flow. The model inference finds repeated substructure, infers
analytical rules to explain substructure scaling (edge branching and
joining), and predicts edge properties such as data accesses, access
size, and data volume.


**Contacts**: (_firstname_._lastname_@pnnl.gov)
  - Nathan R. Tallent ([www](https://hpc.pnnl.gov/people/tallent)), ([www](https://www.pnnl.gov/people/nathan-tallent))
  - Jesun Firoz ([www](https://www.pnnl.gov/people/jesun-firoz))
  - Lenny Guo ([www](https://www.pnnl.gov/people/luanzheng-guo))
  - Meng Tang (Illinois Institute of Technology) ([www](https://scholar.google.com/citations?user=KXC9NesAAAAJ&hl=en))
  - Hyungro Lee ([www](https://www.pnnl.gov/science/staff/staff_info.asp?staff_num=10843)), ([www](https://lee212.github.io/))
  

**Contributors**:
  - Hyungro Lee (PNNL) ([www](https://www.pnnl.gov/science/staff/staff_info.asp?staff_num=10843)), ([www](https://lee212.github.io/))
  - Meng Tang (Illinois Institute of Technology) ([www](https://scholar.google.com/citations?user=KXC9NesAAAAJ&hl=en))
  - Jesun Firoz ([www](https://www.pnnl.gov/people/jesun-firoz))
  - Lenny Guo ([www](https://www.pnnl.gov/people/luanzheng-guo))
  - Nathan R. Tallent (PNNL) ([www](https://hpc.pnnl.gov/people/tallent)), ([www](https://www.pnnl.gov/people/nathan-tallent))



References
-----------------------------------------------------------------------------

* H. Lee, L. Guo, M. Tang, J. Firoz, N. Tallent, A. Kougkas, and X.-H. Sun, “Data flow lifecycles for optimizing workflow coordination,” in Proc. of the Intl. Conf. for High Performance Computing, Networking, Storage and Analysis (SuperComputing), SC ’23, (New York, NY, USA), Association for Computing Machinery, November 2023. ([doi](https://doi.org/10.1145/3581784.3607104))

* M. Tang, J. Cernuda, J. Ye, L. Guo, N. R. Tallent, A. Kougkas, and X.-H. Sun, “DaYu: Optimizing distributed scientific workflows by decoding dataflow semantics and dynamics,” in Proc. of the 2024 IEEE Conf. on Cluster Computing, pp. 357–369, IEEE, September 2024. ([doi](https://doi.org/10.1109/CLUSTER59578.2024.00038))

* L. Guo, H. Lee, J. Firoz, M. Tang, and N. R. Tallent, “Improving I/O-aware workflow scheduling via data flow characterization and trade-off analysis,” in Seventh IEEE Intl. Workshop on Benchmarking, Performance Tuning and Optimization for Big Data Applications (Proc. of the IEEE Intl. Conf. on Big Data), IEEE Computer Society, December 2024.  ([doi](https://doi.org/10.1109/BigData62323.2024.10825855))

* H. Lee, J. Firoz, N. R. Tallent, L. Guo, and M. Halappanavar, “FlowForecaster: Automatically inferring detailed & interpretable workflow scaling models for better scheduling,” in Proc. of the 39th IEEE Intl. Parallel and Distributed Processing Symp., IEEE Computer Society, June 2025.
<!-- ([doi](https://doi.org/10.1145/3581784.3607104)) -->



Acknowledgements
-----------------------------------------------------------------------------

This work was supported by the U.S. Department of Energy's Office of
Advanced Scientific Computing Research:

- Orchestration for Distributed & Data-Intensive Scientific Exploration
