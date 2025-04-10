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


def check_is_data(node: str, attr: dict):
    if "abspath" in attr:
        return True

    ext = os.path.splitext(node)[1]
    if ext in [".vcf", ".gz", ".txt"]:
        return True

    return False


def topological_sort_with_levels(G):
    # Get topological sort
    try:
        topo_order = list(nx.topological_sort(G))
    except Exception as e:
        print(e)
        print("Returns empty...")
        return [], {}
    
    # Initialize levels
    levels = {node: 0 for node in G.nodes()}
    
    # Compute levels
    for node in topo_order:
        # Level of a node is 1 + maximum level of its predecessors
        pred_levels = [levels[pred] for pred in G.predecessors(node)]
        levels[node] = 1 + max(pred_levels) if pred_levels else 0
    
    return topo_order, levels

def find_sources(G):
    sources = []
    # for node, attr in G.nodes(data=True):
    for node in G.nodes:
        if G.in_degree(node) == 0:
            sources.append(node)
    
    return sources


def bfs(filename: str):
    print(f"graphml_file: {filename}")
    G = nx.read_graphml(filename)
    sources = find_sources(G)
    print("\nsources:")
    pprint(sources)

    # # test
    # pos=nx.bfs_layout(G, sources)
    # print("\npos")
    # pprint(pos)
    # sys.exit(-1)
    # # end test

    # TS
    # # results = list(nx.topological_sort(G))
    # # print("TS")
    # # pprint(results)
    # order, levels = topological_sort_with_levels(G)
    # # print("\norder")
    # # pprint(order)
    # print(f"\nlevels(num_nodes:{len(levels)}):")
    # pprint(levels)

    # Topological generations
    generations = nx.topological_generations(G)
    print(f"\nGenerations(topological_generations):")
    for layer, nodes in enumerate(generations):
        print(f"layer: {layer} nodes: {nodes}")
        for node in nodes:
            G.nodes[node]['layer'] = layer
    positions = nx.multipartite_layout(G, subset_key="layer", align='horizontal')

    # sys.exit(-1)
    # end TS
    # Draw
    fig, ax = plt.subplots()
    colors = ['tab:blue' if check_is_data(node, attr) else 'tab:red' for node, attr in G.nodes(data=True)]
    # nx.draw(G, pos=nx.bfs_layout(G, sources, align='horizontal'), with_labels=True, font_size=8, node_color=colors)
    nx.draw_networkx(G, pos=positions, with_labels=True, font_size=8, node_color=colors)
    basename = os.path.splitext(os.path.basename(filename))[0]
    png_filename = f"{basename}.png"
    ax.set_title(png_filename)
    fig.tight_layout()
    fig.savefig(png_filename)
    # plt.savefig(png_filename)
    print(f"\nSaved to {png_filename}")

    # level = 0
    # level_map = {}
    # # visited = set()
    # fronts = []
    # new_fronts = []
    # for curr in sources:
    #     fronts.append(curr)
    #     # if curr not in visited:
    #     #     visited.add(curr)
    #     if curr not in level_map:
    #         # level_map[curr] = {level}
    #         level_map[curr] = SortedSet()
    #         level_map[curr].add(level)
    #     else:
    #         level_map[curr].add(level)
    # level += 1
    #
    # while fronts:
    #     for curr in fronts:
    #         for out in G.successors(curr):
    #             new_fronts.append(out)
    #             # if out not in visited:
    #             #     visited.add(out)
    #             if out not in level_map:
    #                 level_map[out] = SortedSet()
    #                 level_map[out].add(level)
    #             else:
    #                 level_map[out].add(level)
    #     fronts, new_fronts = new_fronts, fronts
    #     new_fronts.clear()
    #     level += 1
    #
    #     if level == 10:
    #         print(f"\nSomething is wrong. Level ({level}) is too large. Probably a loop.")
    #         break
    #
    # print(f"\nlevel_map(num_nodes:{len(level_map)}):")
    # pprint(level_map)
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
    # print_graphml(graphml_file)
    bfs(graphml_file)

    tt_time_end = time.perf_counter()
    print(f"total_exe_time(s): {tt_time_end - tt_time_start}")

