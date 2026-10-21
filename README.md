<!-- -*-Mode: markdown;-*- -->
<!-- $Id: 4098d4ffce45696ec3497ad9e08e712906c9d8fe $ -->


FlowForecaster
=============================================================================

**Home**:
  - [FlowForecaster](https://github.com/pnnl/FlowForecaster), part of [DataFlowDrs](https://github.com/pnnl/DataFlowDrs)
  
  - [Performance Lab for EXtreme Computing and daTa](https://github.com/PerfLab-EXaCT)


**About (Summary)**: To enable high quality scheduling decisions,
FlowForecaster automatically infers detailed and interpretable
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


------------------------------------------------------------------------------
## Contacts

**Contacts**: (_firstname_._lastname_@pnnl.gov)
  - Nathan R. Tallent ([www](https://nathantallent.github.io))
  - Jesun Firoz ([www](https://www.pnnl.gov/people/jesun-firoz))
  - Lenny Guo ([www](https://www.pnnl.gov/people/luanzheng-guo))


**Contributors**:
  - Jesun Firoz ([www](https://www.pnnl.gov/people/jesun-firoz))
  - Zhen Peng ([www](https://johnpzh.github.io))
  - Meng Tang (Illinois Institute of Technology) ([www](https://scholar.google.com/citations?user=KXC9NesAAAAJ&hl=en))
  - Lenny Guo ([www](https://www.pnnl.gov/people/luanzheng-guo))
  - Nathan R. Tallent ([www](https://nathantallent.github.io))


References
-----------------------------------------------------------------------------
- **Overview**: Nathan R. Tallent, Meng Tang, Zhen Peng, Jesun Firoz, Luanzheng Guo, Anthony Kougkas, and Xian-He Sun. "DataFlowDrs: Automating Performance Optimization of Data Flow Within HPC Workflows." IEEE Transactions on Parallel and Distributed Systems, Vol. 37, pp. 2619-2636, December 2026. ([doi: 10.1109/TPDS.2026.3722592](https://doi.org/10.1109/TPDS.2026.3722592))

* **Specific**: Hyungro Lee, Jesun Firoz, Nathan R. Tallent, Luanzheng Guo, and Mahantesh Halappanavar. "FlowForecaster: Automatically Inferring Detailed & Interpretable Workflow Scaling Models for Forecasts" Proc. of the 39th IEEE Intl. Parallel and Distributed Processing Symp., IPDPS '25, pp. 420-432, IEEE Computer Society, June 2025. ([doi: 10.1109/IPDPS64566.2025.00045](https://doi.org/10.1109/IPDPS64566.2025.00045))

- For all related references, see [DataFlowDrs](https://github.com/pnnl/DataFlowDrs)


## License

BSD 2-clause license: [README-License.txt](/README-License.txt)


Acknowledgements
-----------------------------------------------------------------------------

This work was supported by the U.S. Department of Energy's Office of
Advanced Scientific Computing Research:

- Orchestration for Distributed & Data-Intensive Scientific Exploration
