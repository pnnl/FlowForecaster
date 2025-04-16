import sys
import argparse
import time
import os
import numpy as np
import networkx as nx

sys.path.append("../utils")
from py_lib_flowforecaster import EdgeType, VertexType
from py_lib_flowforecaster import EdgeAttrType, VertexAttrType
from py_lib_flowforecaster import show_dag
from py_lib_flowforecaster import check_is_data
from py_lib_flowforecaster import flatten_graph_for_graphml


def get_task_prefix(task):
    return task.rsplit("_taskid", 1)[0]


def get_file_prefix(file):
    return file.rsplit("_fileid", 1)[0]


def get_common_suffix(strings):
    if len(strings) == 1:
        return strings[0]

    common_suffix = strings[0]
    for str_i in range(1, len(strings)):
        curr = strings[str_i]
        i = len(common_suffix) - 1
        j = len(curr) - 1
        suffix = ""
        while i >= 0 and j >= 0 and common_suffix[i] == curr[j]:
            suffix = common_suffix[i] + suffix
            i -= 1
            j -= 1
        common_suffix = suffix

    return common_suffix


def get_compound_file_name(file_vertices):
    filenames = []
    for v in file_vertices:
        basename, ext = os.path.splitext(v)
        basename = basename.split("_fileid")[0]
        filenames.append(basename + ext)

    if len(filenames) == 1:
        return filenames[0]

    common_prefix = os.path.commonprefix(filenames)
    common_suffix = get_common_suffix(filenames)
    if common_prefix == "" and common_suffix == "":
        return filenames[0]
    else:
        return common_prefix + common_suffix


def add_edge_to_graph(G,
                      src,
                      dst,
                      attr):
    G.add_edge(src, dst, **attr)
    # G.nodes[src]["type"] = src_type
    # G.nodes[dst]["type"] = dst_type


def set_vertex_attr(G,
                    vertex,
                    attr):
    for key, val in attr.items():
        G.nodes[vertex][key] = val


def get_first_task_level(vertex_levels, G):
    level = 0
    for vertices in vertex_levels:
        if any(check_is_data(v, G.nodes[v]) for v in vertices):
            # Data level
            level += 1
        else:
            # Task level
            break

    return level


def update_edge_attr(G,
                     src,
                     dst,
                     delta_attr: dict):
    for key, val in delta_attr.items():
        G[src][dst][key].append(val)


def update_vertex_attr(G,
                       vertex,
                       delta_attr: dict):
    for key, val in delta_attr.items():
        G.nodes[vertex][key].append(val)


# def flatten_graph_for_graphml(G):
#     """
#     networkx.exception.NetworkXError: GraphML writer does not support <class 'list'> as data values.
#     Therefore, we need to flatten those list before saving.
#     """
#
#     # Flatten vertex attributes
#     for v, attr in G.nodes(data=True):
#         for key, val in attr.items():
#             if isinstance(val, list):
#                 attr[key] = "[" + ",".join([str(x) for x in val]) + "]"
#             else:
#                 attr[key] = str(val)
#
#     # Flatten edge attributes
#     for src, dst, attr in G.edges(data=True):
#         for key, val in attr.items():
#             if isinstance(val, list):
#                 attr[key] = "[" + ",".join([str(x) for x in val]) + "]"
#             else:
#                 attr[key] = str(val)


def compound(filename: str):
    print(f"graphml_file: {filename}")
    G = nx.read_graphml(filename)

    """
    Topological generations
    """
    generations = nx.topological_generations(G)
    vertex_levels = []
    print(f"\nGenerations(topological_generations):")
    for layer, nodes in enumerate(generations):
        vertex_levels.append(nodes)
        print(f"layer: {layer} nodes: {nodes}")

    """
    Construct the compound graph
    """
    task_prefix_set = set()
    boundary_task_prefix_set = set()
    compound_graph = nx.DiGraph()
    num_levels = len(vertex_levels)
    first_task_level = get_first_task_level(vertex_levels, G=G)
    print(f"first_task_level: {first_task_level} num_levels: {num_levels}")
    boundary_level = 0
    for level in range(first_task_level, num_levels, 2):
        # Iterate the task levels
        tasks = vertex_levels[level]

        # Skip dummy task
        if len(tasks) == 1 and "dummy_task" == get_task_prefix(tasks[0]):
            continue

        # Classify tasks
        task_clusters = {}
        for task in tasks:
            task_prefix = get_task_prefix(task)
            if task_prefix not in task_clusters:
                task_clusters[task_prefix] = set()
            task_clusters[task_prefix].add(task)

        # Detect the boundary
        found_boundary = False
        for task_prefix in task_clusters:
            if task_prefix in task_prefix_set:
                found_boundary = True
                boundary_task_prefix_set.add(task_prefix)
            else:
                task_prefix_set.add(task_prefix)
        if found_boundary:
            boundary_level = level
            break

        # Add edges from files to tasks
        for task_prefix, tasks in task_clusters.items():
            if len(tasks) > 1:
                # Could be a fan-out edge
                # find out all possible sources to this cluster
                source_to_ends_info = {}
                for task in tasks:
                    for src in G.predecessors(task):
                        if src not in source_to_ends_info:
                            source_to_ends_info[src] = {
                                "num_dsts": 0,
                                "data_volumes": [],
                                "access_sizes": []
                            }
                        # Get edge statistics
                        source_to_ends_info[src]["num_dsts"] += 1
                        source_to_ends_info[src]["data_volumes"].append(np.float64(G[src][task][EdgeAttrType.DATA_VOL]))
                        source_to_ends_info[src]["access_sizes"].append(np.float64(G[src][task][EdgeAttrType.ACC_SIZE]))
                # Add the compound edge
                for src, info in source_to_ends_info.items():
                    file_name = get_compound_file_name([src])
                    if info["num_dsts"] > 1:
                        """
                        Fan-out edge
                        """
                        add_edge_to_graph(G=compound_graph,
                                          src=file_name,
                                          dst=task_prefix,
                                          attr={
                                              EdgeAttrType.TYPE: EdgeType.FAN_OUT,
                                              EdgeAttrType.NUM_SRC: 1,
                                              EdgeAttrType.NUM_DST: [info["num_dsts"]],
                                              EdgeAttrType.DATA_VOL: [np.mean(info["data_volumes"])],  # mean or sum
                                              EdgeAttrType.ACC_SIZE: [np.mean(info["access_sizes"])]
                                          })
                        if level == 1:
                            # Set level 0 files
                            set_vertex_attr(G=compound_graph,
                                            vertex=file_name,
                                            attr={
                                                VertexAttrType.TYPE: VertexType.FILE,
                                                VertexAttrType.SIZE: [np.float64(G.nodes[src][VertexAttrType.SIZE])]
                                            })
                        set_vertex_attr(G=compound_graph,
                                        vertex=task_prefix,
                                        attr={
                                            VertexAttrType.TYPE: VertexType.TASK,
                                        })
                    elif info["num_dsts"] == 1:
                        """
                        Sequential edge
                        """
                        add_edge_to_graph(G=compound_graph,
                                          src=src,
                                          dst=task_prefix,
                                          attr={
                                              EdgeAttrType.TYPE: EdgeType.SEQ,
                                              EdgeAttrType.NUM_SRC: 1,
                                              EdgeAttrType.NUM_DST: 1,
                                              EdgeAttrType.DATA_VOL: [info["data_volumes"][0]],
                                              EdgeAttrType.ACC_SIZE: [info["access_sizes"][0]]
                                          })
                        if level == 1:
                            # Set level 0 files
                            set_vertex_attr(G=compound_graph,
                                            vertex=src,
                                            attr={
                                                VertexAttrType.TYPE: VertexType.FILE,
                                                VertexAttrType.SIZE: [np.float64(G.nodes[src][VertexAttrType.SIZE])]
                                            })
                        set_vertex_attr(G=compound_graph,
                                        vertex=task_prefix,
                                        attr={
                                            VertexAttrType.TYPE: VertexType.TASK,
                                        })
                    else:
                        raise Exception(f"Should never happen. info={info}")
                pass  # end Could be a fan-out edge
            elif len(tasks) == 1:
                # Could be a fin-in edge
                task = next(iter(tasks))  # the only element
                if G.in_degree(task) > 1:
                    """
                    Fin-in edge
                    """
                    # Get edge statistics
                    info = {
                        "data_volumes": [],
                        "access_sizes": []
                    }
                    for src in G.predecessors(task):
                        info["data_volumes"].append(np.float64(G[src][task][EdgeAttrType.DATA_VOL]))
                        info["access_sizes"].append(np.float64(G[src][task][EdgeAttrType.ACC_SIZE]))
                    file_name = get_compound_file_name(G.predecessors(task))
                    # Add the compound edge
                    add_edge_to_graph(G=compound_graph,
                                      src=file_name,
                                      dst=task_prefix,
                                      attr={
                                          EdgeAttrType.TYPE: EdgeType.FAN_IN,
                                          EdgeAttrType.NUM_SRC: [G.in_degree(task)],
                                          EdgeAttrType.NUM_DST: 1,
                                          EdgeAttrType.DATA_VOL: [np.mean(info["data_volumes"])],
                                          EdgeAttrType.ACC_SIZE: [np.mean(info["access_sizes"])]
                                      })
                    if level == 1:
                        # Set level 0 files
                        set_vertex_attr(G=compound_graph,
                                        vertex=file_name,
                                        attr={
                                            VertexAttrType.TYPE: VertexType.FILE,
                                            VertexAttrType.SIZE: [np.mean(G.predecessors(task))]
                                        })
                    set_vertex_attr(G=compound_graph,
                                    vertex=task_prefix,
                                    attr={
                                        VertexAttrType.TYPE: VertexType.TASK,
                                    })
                elif G.in_degree(task) == 1:
                    """
                    Sequential edge
                    """
                    src = next(iter(G.predecessors(task)))  # the only predecessor
                    file_name = get_compound_file_name([src])
                    # Add the compound edge
                    add_edge_to_graph(G=compound_graph,
                                      src=file_name,
                                      dst=task_prefix,
                                      attr={
                                          EdgeAttrType.TYPE: EdgeType.SEQ,
                                          EdgeAttrType.NUM_SRC: 1,
                                          EdgeAttrType.NUM_DST: 1,
                                          EdgeAttrType.DATA_VOL: [np.float64(G[src][task][EdgeAttrType.DATA_VOL])],
                                          EdgeAttrType.ACC_SIZE: [np.float64(G[src][task][EdgeAttrType.ACC_SIZE])]
                                      })
                    if level == 1:
                        # Set level 0 files
                        set_vertex_attr(G=compound_graph,
                                        vertex=file_name,
                                        attr={
                                            VertexAttrType.TYPE: VertexType.FILE,
                                            VertexAttrType.SIZE: [np.float64(G.nodes[src]["size"])]
                                        })
                    set_vertex_attr(G=compound_graph,
                                    vertex=task_prefix,
                                    attr={
                                        VertexAttrType.TYPE: VertexType.TASK
                                    })
                else:
                    raise Exception(f"Should never happen. G.predecessors(task) = {G.predecessors(task)}")
                pass  # end Could be a fin-in edge
            else:
                raise Exception(f"Should never happen. len(tasks) = {len(tasks)}")

        """
        Assume a task must produces a file
        Add edges from tasks to sequential files. These edges are all sequential.
        """
        for task_prefix, tasks in task_clusters.items():
            # Get files statistics
            info = {
                "files": [],
                "data_volumes": [],
                "access_sizes": [],
                "sizes": []}
            for task in tasks:
                for file in G.successors(task):
                    info["files"].append(file)
                    info["data_volumes"].append(np.float64(G[task][file][EdgeAttrType.DATA_VOL]))
                    info["access_sizes"].append(np.float64(G[task][file][EdgeAttrType.ACC_SIZE]))
                    info["sizes"].append(np.float64(G.nodes[file][VertexAttrType.SIZE]))
            file_name = get_compound_file_name(info["files"])
            # Add the compound edge
            add_edge_to_graph(G=compound_graph,
                              src=task_prefix,
                              dst=file_name,
                              attr={
                                  EdgeAttrType.TYPE: EdgeType.SEQ,
                                  EdgeAttrType.NUM_SRC: 1,
                                  EdgeAttrType.NUM_DST: 1,
                                  EdgeAttrType.DATA_VOL: [np.mean(info["data_volumes"])],
                                  EdgeAttrType.ACC_SIZE: [np.mean(info["access_sizes"])]
                              })
            set_vertex_attr(G=compound_graph,
                            vertex=file_name,
                            attr={
                                VertexAttrType.TYPE: VertexType.FILE,
                                VertexAttrType.SIZE: [np.mean(info["sizes"])]
                            })

        pass  # end this level

    # test
    # print(f"boundary_level: {boundary_level}")
    # show_dag(compound_graph)
    # basename = os.path.splitext(os.path.basename(filename))[0]
    # compound_filename = f"{basename}.compound.graphml"
    # nx.write_graphml(G=compound_graph, path=compound_filename)
    # end test

    print(f"compound_graph: num_nodes: {compound_graph.number_of_nodes()} num_edges: {compound_graph.number_of_edges()}")

    """
    Return results
    """
    results = {
        "filename": filename,
        "compound_graph": compound_graph,
        "origin_graph": G,
        "vertex_levels": vertex_levels,
        "boundary_level": boundary_level,
        "boundary_task_prefix_set": boundary_task_prefix_set
    }
    return results


def collect_statistics(filename: str,
                       compound_graph,
                       origin_graph,
                       vertex_levels: list,
                       boundary_level: int,
                       boundary_task_prefix_set: set):
    """
    Continue traverse, collect statistics into the compound graph.
    """
    num_levels = len(vertex_levels)
    start_level = boundary_level
    print(f"start level: {start_level} num_levels: {num_levels}")
    for level in range(start_level, num_levels, 2):
        # Iterate the task levels
        tasks = vertex_levels[level]

        # Skip dummy task
        if len(tasks) == 1 and "dummy_task" == get_task_prefix(tasks[0]):
            continue

        # Classify tasks
        task_clusters = {}
        for task in tasks:
            task_prefix = get_task_prefix(task)
            if task_prefix not in task_clusters:
                task_clusters[task_prefix] = set()
            task_clusters[task_prefix].add(task)

        current_is_boundary = False
        for task_prefix in task_clusters:
            if task_prefix in boundary_task_prefix_set:
                current_is_boundary = True

        # Exam edges from files to current tasks
        for task_prefix, tasks in task_clusters.items():
            if len(tasks) > 1:
                # Could be a fan-out edge
                # find out all possible sources to this cluster
                source_to_ends_info = {}
                for task in tasks:
                    for src in origin_graph.predecessors(task):
                        if src not in source_to_ends_info:
                            source_to_ends_info[src] = {
                                "num_dsts": 0,
                                "data_volumes": [],
                                "access_sizes": []
                            }
                        # Get edge statistics
                        source_to_ends_info[src]["num_dsts"] += 1
                        source_to_ends_info[src]["data_volumes"].append(np.float64(origin_graph[src][task][EdgeAttrType.DATA_VOL]))
                        source_to_ends_info[src]["access_sizes"].append(np.float64(origin_graph[src][task][EdgeAttrType.ACC_SIZE]))
                # Update the compound edge attributes
                for src, info in source_to_ends_info.items():
                    file_name = get_compound_file_name([src])
                    if info["num_dsts"] > 1:
                        """
                        Fan-out edge
                        """
                        update_edge_attr(G=compound_graph,
                                         src=file_name,
                                         dst=task_prefix,
                                         delta_attr={
                                             EdgeAttrType.NUM_DST: info["num_dsts"],
                                             EdgeAttrType.DATA_VOL: np.mean(info["data_volumes"]),
                                             EdgeAttrType.ACC_SIZE: np.mean(info["access_sizes"]),
                                         })
                        if current_is_boundary:
                            # Update "root" level files
                            update_vertex_attr(G=compound_graph,
                                               vertex=file_name,
                                               delta_attr={
                                                   VertexAttrType.SIZE: np.float64(origin_graph.nodes[src][VertexAttrType.SIZE])
                                               })
                    elif info["num_dsts"] == 1:
                        """
                        Sequential edge
                        """
                        update_edge_attr(G=compound_graph,
                                         src=src,
                                         dst=task_prefix,
                                         delta_attr={
                                             EdgeAttrType.DATA_VOL: info["data_volumes"][0],
                                             EdgeAttrType.ACC_SIZE: info["access_sizes"][0]
                                         })
                        if current_is_boundary:
                            # Update "root" level files
                            update_vertex_attr(G=compound_graph,
                                               vertex=src,
                                               delta_attr={
                                                   VertexAttrType.SIZE: np.float64(origin_graph.nodes[src][VertexAttrType.SIZE])
                                               })
                    else:
                        raise Exception(f"Should never happen. info={info}")
                pass  # end Could be a fan-out edge
            elif len(tasks) == 1:
                # Could be a fin-in edge
                task = next(iter(tasks))  # the only element
                if origin_graph.in_degree(task) > 1:
                    """
                    Fin-in edge
                    """
                    # Get edge statistics
                    info = {
                        "data_volumes": [],
                        "access_sizes": []
                    }
                    for src in origin_graph.predecessors(task):
                        info["data_volumes"].append(np.float64(origin_graph[src][task][EdgeAttrType.DATA_VOL]))
                        info["access_sizes"].append(np.float64(origin_graph[src][task][EdgeAttrType.ACC_SIZE]))
                    file_name = get_compound_file_name(origin_graph.predecessors(task))
                    # Update the compound edge
                    update_edge_attr(G=compound_graph,
                                     src=file_name,
                                     dst=task_prefix,
                                     delta_attr={
                                         EdgeAttrType.NUM_SRC: origin_graph.in_degree(task),
                                         EdgeAttrType.DATA_VOL: np.mean(info["data_volumes"]),
                                         EdgeAttrType.ACC_SIZE: np.mean(info["access_sizes"])
                                     })
                    if current_is_boundary:
                        # Update "root" level files
                        update_vertex_attr(G=compound_graph,
                                           vertex=file_name,
                                           delta_attr={
                                               VertexAttrType.SIZE: np.mean(origin_graph.predecessors(task))
                                           })
                elif origin_graph.in_degree(task) == 1:
                    """
                    Sequential edge
                    """
                    src = next(iter(origin_graph.predecessors(task)))  # the only predecessor
                    file_name = get_compound_file_name([src])
                    # Update the compound edge
                    update_edge_attr(G=compound_graph,
                                     src=file_name,
                                     dst=task_prefix,
                                     delta_attr={
                                         EdgeAttrType.DATA_VOL: np.float64(origin_graph[src][task][EdgeAttrType.DATA_VOL]),
                                         EdgeAttrType.ACC_SIZE: np.float64(origin_graph[src][task][EdgeAttrType.ACC_SIZE])
                                     })
                    if current_is_boundary:
                        # Update "root" level files
                        update_vertex_attr(G=compound_graph,
                                           vertex=file_name,
                                           delta_attr={
                                               VertexAttrType.SIZE: np.float64(origin_graph.nodes[src]["size"])
                                           })
                else:
                    raise Exception(f"Should never happen. origin_graph.predecessors(task) = {origin_graph.predecessors(task)}")
                pass  # end Could be a fin-in edge
            else:
                raise Exception(f"Should never happen. len(tasks) = {len(tasks)}")

        """
        Update the edges from tasks to following files. These edges are all sequential.
        TODO: might not be sequential.
        """
        for task_prefix, tasks in task_clusters.items():
            # Get files statistics
            info = {
                "files": [],
                "data_volumes": [],
                "access_sizes": [],
                "sizes": []}
            for task in tasks:
                for file in origin_graph.successors(task):
                    info["files"].append(file)
                    info["data_volumes"].append(np.float64(origin_graph[task][file][EdgeAttrType.DATA_VOL]))
                    info["access_sizes"].append(np.float64(origin_graph[task][file][EdgeAttrType.ACC_SIZE]))
                    info["sizes"].append(np.float64(origin_graph.nodes[file][VertexAttrType.SIZE]))
            file_name = get_compound_file_name(info["files"])
            # Update the compound edge
            update_edge_attr(G=compound_graph,
                             src=task_prefix,
                             dst=file_name,
                             delta_attr={
                                 EdgeAttrType.DATA_VOL: np.mean(info["data_volumes"]),
                                 EdgeAttrType.ACC_SIZE: np.mean(info["access_sizes"])
                             })
            update_vertex_attr(G=compound_graph,
                               vertex=file_name,
                               delta_attr={
                                   VertexAttrType.SIZE: np.mean(info["sizes"])
                               })

        pass  # end this level

    # test
    # show_dag(compound_graph)
    basename = os.path.splitext(os.path.basename(filename))[0]
    compound_filename = f"{basename}.statistic.graphml"
    flatten_graph_for_graphml(G=compound_graph)
    nx.write_graphml(G=compound_graph, path=compound_filename)
    # end test


if __name__ == "__main__":
    parser = argparse.ArgumentParser(f"{sys.argv[0]}")
    parser.add_argument("graphml_file", type=str, help="input GraphML file")
    # parser.add_argument("-i", "--iterations", type=int, default=3, help="number of iterations to synthesize")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(-1)
    args = parser.parse_args()

    tt_time_start = time.perf_counter()

    graphml_file = args.graphml_file
    compound_results = compound(graphml_file)
    collect_statistics(**compound_results)

    tt_time_end = time.perf_counter()
    print(f"total_exe_time(s): {tt_time_end - tt_time_start}")