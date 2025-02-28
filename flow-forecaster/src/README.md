Flow Forecaster Quick Guide:
===============================================================================

This page introduces Flow Forecaster calls in the following order:

  - flow_forecaster.sbatch
   : initializing slurm job scheduler 

  - get_sh
   : read and parse input data

  - gen_edgelist
   : write edgelist

  - parse_dfls
   : write edgelist in a graph format

  - final_results
   : collect a set of results

  - predict_dfls
   : meet an high accuracy


Flow Forescaster Installation (Example)
-------------------------------------------------------------------------------

  $ pip install .

    ...

    Building wheels for collected packages: flow-forecaster
      Building wheel for flow-forecaster (setup.py) ... done
      Created wheel for flow-forecaster: filename=flow_forecaster-0.1.1-py3-none-any.whl size=1447 sha256=30fc74b1e692536c949b8a142dd34d2936f02263332cdc226d329268595bb529
      Stored in directory: /tmp/pip-ephem-wheel-cache-gnklxxgj/wheels/9e/0e/c3/39019e3d48132f46ea28a26fb95abe001bc32ce0297c3cc35f
    Successfully built flow-forecaster
    Installing collected packages: flow-forecaster
      Attempting uninstall: flow-forecaster
        Found existing installation: flow-forecaster 0.1.1
        Uninstalling flow-forecaster-0.1.1:
          Successfully uninstalled flow-forecaster-0.1.1
    Successfully installed flow-forecaster-0.1.1

