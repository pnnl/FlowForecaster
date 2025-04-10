import os
from enum import Enum
import networkx as nx
import matplotlib.pyplot as plt


# class EdgeType(str, Enum):
class EdgeType:
    FAN_OUT = "fan-out"
    FAN_IN = "fan-in"
    SEQ = "sequential"


class EdgeAttrType:
    TYPE = "type"
    DATA_VOL = "data_volume"
    ACC_SIZE = "access_size"
    NUM_SRC = "num_sources"
    NUM_DST = "num_destinations"
    # NUM_TASKS = "num_tasks"
    # NUM_FILES = "num_files"


# class VertexType(str, Enum):
class VertexType:
    FILE = "file"
    TASK = "task"


class VertexAttrType:
    TYPE = "type"
    SIZE = "size"


def check_is_data(node: str, attr: dict):
    if attr.get("type") == VertexType.FILE:
        return True

    if "abspath" in attr:
        return True

    ext = os.path.splitext(node)[1]
    if ext in [".vcf", ".gz", ".txt", ".h5", ".dcd", ".pt", ".pdb", ".json"]:
        return True

    return False


def show_dag(G):
    # print(f"graphml_file: {filename}")
    # G = nx.read_graphml(filename)

    # Topological generations
    try:
        generations = nx.topological_generations(G)
        print(f"\nGenerations(topological_generations):")
        for layer, nodes in enumerate(generations):
            # print(f"layer: {layer} nodes: {nodes}")
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

    # edge_labels = {(src, dst): attr for src, dst, attr in G.edges(data=True)}
    # nx.draw_networkx_edge_labels(G, pos=positions, edge_labels=edge_labels)

    basename = "output.figure"
    png_filename = f"{basename}.png"
    ax.set_title(png_filename)
    fig.tight_layout()
    fig.savefig(png_filename)
    print(f"\nSaved to {png_filename}")
    print(f"\nnum_nodes: {G.number_of_nodes()} num_edges: {G.number_of_edges()}")
    plt.show()