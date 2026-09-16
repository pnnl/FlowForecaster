import json
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
    # Number of accesses.  The paper (Sec. III-A) treats accesses and access
    # size as the base metrics and volume as derived.  Traced instances record
    # only volume and access size, so accesses is recovered as A = V / S.
    ACCESSES = "accesses"
    # Fan-in aggregate volume, Eq. 1: V_sigma(v) = sum of V(e) over e in E^-(v).
    VOL_AGGREGATE = "volume_aggregate"
    # NUM_TASKS = "num_tasks"
    # NUM_FILES = "num_files"


def utils_dir():
    """
    Absolute path of this directory.

    Modules under src/ used to do `sys.path.append("../utils")`, which only
    works when the interpreter's working directory happens to be src/.  They
    now resolve the path from __file__ instead.
    """
    return os.path.dirname(os.path.abspath(__file__))


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


def show_dag(G, msg="test"):
    # print(f"graphml_file: {filename}")
    # G = nx.read_graphml(filename)

    # Topological generations
    try:
        generations = nx.topological_generations(G)
        # print(f"\nGenerations(topological_generations):")
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
    png_filename = f"{basename}.{msg}.png"
    ax.set_title(png_filename)
    fig.tight_layout()
    fig.savefig(png_filename)
    print(f"Saved to {png_filename}")
    print(f"{msg}.num_nodes: {G.number_of_nodes()} {msg}.num_edges: {G.number_of_edges()}")
    plt.show()


def flatten_graph_for_graphml(G):
    """
    networkx.exception.NetworkXError: GraphML writer does not support <class 'list'> as data values.
    Therefore, we need to flatten those list before saving.
    """

    # Flatten vertex attributes
    for v, attr in G.nodes(data=True):
        for key, val in attr.items():
            attr[key] = f"{val}"

    # Flatten edge attributes
    for src, dst, attr in G.edges(data=True):
        for key, val in attr.items():
            attr[key] = f"{val}"

def _jsonable(value):
    """Coerce numpy scalars, tuples and sets into plain JSON-representable values."""
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return str(value)


def encode_graph_for_graphml(G):
    """
    Return a *copy* of G whose attribute values are all GraphML-safe strings.

    Two differences from flatten_graph_for_graphml():

    1. It does not mutate G.  The caller can keep using the live graph after
       writing it, which is what the projection path needs -- flattening in
       place turned every list attribute into a Python repr and silently broke
       downstream `isinstance(x, list)` checks.
    2. Structured values are JSON-encoded rather than f-string formatted, so
       read_graphml_decoded() can recover them exactly.
    """
    H = G.copy()  # new attribute dicts, shared values -- safe to overwrite
    for _, attr in H.nodes(data=True):
        for key, val in list(attr.items()):
            attr[key] = val if isinstance(val, str) else json.dumps(_jsonable(val))
    for _, _, attr in H.edges(data=True):
        for key, val in list(attr.items()):
            attr[key] = val if isinstance(val, str) else json.dumps(_jsonable(val))
    return H


def write_graphml_encoded(G, path):
    """
    Write G to GraphML without disturbing the in-memory graph.

    Creates the containing directory if it is missing.  Every caller writes its
    output after the inference is finished, so a path whose directory does not
    exist used to throw away the whole run's work at the last step.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    nx.write_graphml(encode_graph_for_graphml(G), path)


def _decode_attr(text):
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def read_graphml_decoded(path):
    """Read a GraphML file written by write_graphml_encoded(), restoring structure."""
    G = nx.read_graphml(path)
    for _, attr in G.nodes(data=True):
        for key, val in list(attr.items()):
            attr[key] = _decode_attr(val)
    for _, _, attr in G.edges(data=True):
        for key, val in list(attr.items()):
            attr[key] = _decode_attr(val)
    return G
