import sys
import os
import argparse
import time
import networkx as nx
import numpy as np
import matplotlib.pyplot as plt
from pprint import pprint
import pandas as pd
from sortedcontainers import SortedSet

sys.path.append("../utils")
from py_lib_flowforecaster import check_is_data



def print_graphml(filename: str):
    print(f"graphml_file: {filename}")
    G = nx.read_graphml(filename)

    # Topological generations
    try:
        generations = nx.topological_generations(G)
        print(f"\nGenerations(topological_generations):")
        for layer, nodes in enumerate(generations):
            print(f"layer: {layer} nodes: {nodes}")
            for node in nodes:
                G.nodes[node]['layer'] = layer
        positions = nx.multipartite_layout(G, subset_key="layer", align='horizontal')
    except Exception as e:
        print(e)
        print(f"Using bfs_layout...")
        sources = [node for node in G.nodes if G.in_degree(node) == 0]
        positions = nx.bfs_layout(G, sources)

    # Draw
    fig, ax = plt.subplots()
    colors = ['tab:blue' if check_is_data(node, attr) else 'tab:red' for node, attr in G.nodes(data=True)]
    nx.draw_networkx(G, pos=positions, with_labels=True, font_size=8, node_color=colors)

    basename = os.path.splitext(os.path.basename(filename))[0]
    png_filename = f"{basename}.png"
    ax.set_title(png_filename)
    fig.tight_layout()
    fig.savefig(png_filename)
    print(f"\nSaved to {png_filename}")
    print(f"\nnum_nodes: {G.number_of_nodes()} num_edges: {G.number_of_edges()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(f"{sys.argv[0]}")
    parser.add_argument("graphml_file", type=str, help="input GraphML file")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(-1)
    args = parser.parse_args()

    tt_time_start = time.perf_counter()

    graphml_file = args.graphml_file
    print_graphml(graphml_file)

    tt_time_end = time.perf_counter()
    print(f"total_exe_time(s): {tt_time_end - tt_time_start}")

