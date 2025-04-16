import sys
import argparse
import time
import os
import pickle
import networkx as nx

sys.path.append("../utils")
from py_lib_flowforecaster import show_dag
from py_lib_flowforecaster import flatten_graph_for_graphml

def read_gpickle(filename):
    with open(filename, "rb") as fin:
        G = pickle.load(fin)
        show_dag(G)

        #
        flatten_graph_for_graphml(G=G)
        basename = os.path.splitext(os.path.basename(filename))[0]
        graphml_filename = basename + ".graphml"
        nx.write_graphml(G, graphml_filename)
        print(f"Saved to graphml file {graphml_filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(f"{sys.argv[0]}")
    parser.add_argument("gpickle_file", type=str, help="input gpickle file")
    # parser.add_argument("-i", "--iterations", type=int, default=3, help="number of iterations to synthesize")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(-1)
    args = parser.parse_args()

    tt_time_start = time.perf_counter()

    gpickle_file = args.gpickle_file
    read_gpickle(gpickle_file)

    tt_time_end = time.perf_counter()
    print(f"total_exe_time(s): {tt_time_end - tt_time_start}")