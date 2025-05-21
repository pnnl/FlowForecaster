import sys
import argparse
import time
import os
from collections import defaultdict
import numpy as np
import networkx as nx

sys.path.append("../utils")
from py_lib_flowforecaster import EdgeType, VertexType
from py_lib_flowforecaster import EdgeAttrType, VertexAttrType
from py_lib_flowforecaster import show_dag
from py_lib_flowforecaster import check_is_data
from py_lib_flowforecaster import flatten_graph_for_graphml

# Import rule engine and pattern detection
from rule_engine_auto import match_rule_based_on_patterns, Rule8
from scaling_pattern_detector import (
    compute_scaling_factors, 
    detect_scaling_pattern,
    analyze_edge_scaling,
    infer_overall_scaling_type
)

# Import necessary functions from the original space-time folding code
from do_space_time_folding import (
    divide_threads, 
    construct_compound_graph,
    fold_thread_first_iteration,
    fold_thread_all_iterations, 
    get_task_prefix,
    get_compound_file_name, 
    get_first_task_level
)


def process_instances_for_scaling_type(instance_files: list, scaling_type: str) -> tuple:
    """
    Process multiple instances and perform space-time folding to derive core graphs
    before inferring scaling rules
    
    Args:
        instance_files: List of workflow instance files
        scaling_type: Type of scaling being analyzed ("data" or "task")
    
    Returns:
        Tuple of (all_core_graphs, edge_statistics)
    """
    all_core_graphs = []
    edge_statistics = defaultdict(lambda: {
        "data_volumes": [],
        "access_sizes": [],
        "accesses": [],
        "num_sources": [],
        "num_destinations": [],
        "pattern": None,
        "instances": []
    })
    
    # Process each instance
    for idx, instance_file in enumerate(instance_files):
        print(f"\nProcessing {instance_file} for {scaling_type} scaling...")
        
        # Step 1: Divide threads
        threads_list = divide_threads(filename=instance_file)
        print(f"  Found {len(threads_list)} threads")
        
        # Step 2: Construct compound graph from first thread
        compound_results = construct_compound_graph(G=threads_list[0])
        compound_graph = compound_results["compound_graph"]
        boundary_task_prefix_set = compound_results["boundary_task_prefix_set"]
        
        # Step 3: Perform space folding
        first_iteration_snapshots = [compound_results]
        for t_i in range(1, len(threads_list)):
            workflow_thread = threads_list[t_i]
            result = fold_thread_first_iteration(
                compound_graph=compound_graph,
                G=workflow_thread,
                boundary_task_prefix_set=boundary_task_prefix_set)
            first_iteration_snapshots.append(result)
        
        # Step 4: Perform time folding
        for thread_i, snapshot in enumerate(first_iteration_snapshots):
            fold_thread_all_iterations(workflow_thread_id=thread_i, **snapshot)
        
        # Now compound_graph has undergone both space and time folding,
        # making it a proper core graph as described in the paper
        all_core_graphs.append(compound_graph)
        
        # Collect statistics for each edge in the core graph
        for src, dst, edge_data in compound_graph.edges(data=True):
            edge_key = (src, dst)
            stats = edge_statistics[edge_key]
            
                   
            # Extract metrics - handle both nested lists and simple values
            volume = edge_data.get(EdgeAttrType.DATA_VOL, [[1]])
            if isinstance(volume, list) and len(volume) > 0:
                if isinstance(volume[0], list):
                    volume = volume[0][0]  # Handle nested list
                else:
                    volume = volume[0]  # Handle simple list
            elif isinstance(volume, (int, float)):
                volume = volume  # Already a number
            else:
                volume = 1  # Default
            
            access_size = edge_data.get(EdgeAttrType.ACC_SIZE, [[1]])
            if isinstance(access_size, list) and len(access_size) > 0:
                if isinstance(access_size[0], list):
                    access_size = access_size[0][0]  # Handle nested list
                else:
                    access_size = access_size[0]  # Handle simple list
            elif isinstance(access_size, (int, float)):
                access_size = access_size  # Already a number
            else:
                access_size = 1  # Default
            
            num_src = edge_data.get(EdgeAttrType.NUM_SRC, 1)
            if isinstance(num_src, list) and len(num_src) > 0:
                if isinstance(num_src[0], list):
                    num_src = num_src[0][0]  # Handle nested list
                else:
                    num_src = num_src[0]  # Handle simple list
            elif isinstance(num_src, (int, float)):
                num_src = num_src  # Already a number
            else:
                num_src = 1  # Default
            
            num_dst = edge_data.get(EdgeAttrType.NUM_DST, [[1]])
            if isinstance(num_dst, list) and len(num_dst) > 0:
                if isinstance(num_dst[0], list):
                    num_dst = num_dst[0][0]  # Handle nested list
                else:
                    num_dst = num_dst[0]  # Handle simple list
            elif isinstance(num_dst, (int, float)):
                num_dst = num_dst  # Already a number
            else:
                num_dst = 1  # Default

            
            # Determine pattern type
            pattern = edge_data.get(EdgeAttrType.TYPE)
            if pattern:
                # Convert to string if it's an enum
                if hasattr(pattern, 'value'):
                    pattern = pattern.value
            else:
                # Try to infer pattern from structure
                if compound_graph.in_degree(dst) > 1:
                    pattern = EdgeType.FAN_IN
                elif compound_graph.out_degree(src) > 1:
                    pattern = EdgeType.FAN_OUT
                else:
                    pattern = EdgeType.SEQ
            
            stats["data_volumes"].append(float(volume))
            stats["access_sizes"].append(float(access_size))
            stats["num_sources"].append(int(num_src))
            stats["num_destinations"].append(int(num_dst))
            stats["pattern"] = pattern
            stats["instances"].append(instance_file)
    
    # Analyze scaling patterns for each edge
    for edge_key, stats in edge_statistics.items():
        print(f"\nAnalyzing edge {edge_key}:")
        print(f"  Volumes: {stats['data_volumes']}")
        print(f"  Access sizes: {stats['access_sizes']}")
        
        # Compute scaling factors and detect patterns
        values_dict = {
            "volume": stats["data_volumes"],
            "access_size": stats["access_sizes"],
            "num_destinations": stats["num_destinations"]
        }
        
        scaling_analysis = analyze_edge_scaling(values_dict)
        
        # Update statistics with analysis results
        for key, value in scaling_analysis.items():
            stats[key] = value
        
        print(f"  Pattern: {stats['pattern']}")
        print(f"  Volume pattern: {stats['volume_pattern']}")
        print(f"  Access size pattern: {stats['access_size_pattern']}")
    
    return all_core_graphs, edge_statistics

def infer_rules_for_scaling_type(edge_statistics: dict, scaling_type: str) -> dict:
    """
    Infer rules based on automatically detected scaling patterns
    
    Args:
        edge_statistics: Dictionary of edge statistics
        scaling_type: Type of scaling ("data" or "task")
    
    Returns:
        Dictionary of edge rules
    """
    edge_rules = {}
    
    for edge_key, stats in edge_statistics.items():
        src, dst = edge_key
        print(f"\nInferring rule for edge ({src}, {dst}) - {scaling_type} scaling:")
        
        # Prepare stats for rule matching
        rule_stats = {
            "pattern": stats["pattern"],
            "data_volumes": stats["data_volumes"],
            "access_sizes": stats["access_sizes"],
            "accesses": stats.get("accesses", [10] * len(stats["data_volumes"])),
            "num_consumers": stats["num_destinations"],
            "num_sources": stats["num_sources"],
            "volume_pattern": stats.get("volume_pattern", ("unknown", {})),
            "access_size_pattern": stats.get("access_size_pattern", ("unknown", {})),
            "scaling_type": scaling_type
        }
        
        # Match rule based on patterns
        rule = match_rule_based_on_patterns(rule_stats, stats["pattern"], scaling_type)
        
        edge_rules[edge_key] = {
            "rule": rule,
            "statistics": stats,
            "confidence": calculate_rule_confidence(stats, rule)
        }
        
        print(f"  Pattern: {stats['pattern']}")
        print(f"  Volume pattern: {stats.get('volume_pattern', 'unknown')}")
        print(f"  Matched rule: {rule}")
        # print(f"  Confidence: {edge_rules[edge_key]['confidence']:.2f}")
    
    return edge_rules


def calculate_rule_confidence(stats: dict, rule) -> float:
    """
    Calculate confidence score for rule matching
    
    Returns:
        Confidence score between 0 and 1
    """
    if isinstance(rule, Rule8):
        return 0.5  # Default confidence for empirical rule
    
    # Check how well the pattern matches
    volume_pattern, volume_params = stats.get("volume_pattern", ("unknown", {}))
    access_pattern, access_params = stats.get("access_size_pattern", ("unknown", {}))
    
    confidence = 1.0
    
    # Reduce confidence for unknown patterns
    if volume_pattern == "unknown":
        confidence *= 0.7
    if access_pattern == "unknown":
        confidence *= 0.9
    
    # Increase confidence for more data points
    num_instances = len(stats.get("data_volumes", []))
    if num_instances >= 3:
        confidence *= 1.0
    elif num_instances == 2:
        confidence *= 0.8
    else:
        confidence *= 0.6
    
    return min(confidence, 1.0)


def create_canonical_model_with_rules(core_graphs: list, edge_rules: dict, scaling_type: str) -> nx.DiGraph:
    """
    Create a canonical model by annotating a core graph with rules and statistics
    
    Args:
        core_graphs: List of core graphs from space-time folding
        edge_rules: Dictionary of edge rules
        scaling_type: Type of scaling
    
    Returns:
        Annotated canonical model
    """
    # Use the first core graph as the base for our canonical model
    canonical_model = core_graphs[0].copy()
    
    # Annotate edges with rules and statistics
    for src, dst, edge_data in canonical_model.edges(data=True):
        edge_key = (src, dst)
        
        if edge_key in edge_rules:
            rule_info = edge_rules[edge_key]
            
            # Add rule information
            edge_data["rule"] = rule_info["rule"]
            edge_data["rule_id"] = rule_info["rule"].rule_id
            edge_data["rule_name"] = rule_info["rule"].name
            edge_data["rule_confidence"] = rule_info["confidence"]
            edge_data["scaling_type"] = scaling_type
            
            # Add statistical information
            stats = rule_info["statistics"]
            edge_data["observed_volumes"] = stats["data_volumes"]
            edge_data["observed_access_sizes"] = stats["access_sizes"]
            edge_data["volume_factors"] = stats.get("volume_factors", [])
            edge_data["volume_pattern"] = str(stats.get("volume_pattern", ("unknown", {})))
            edge_data["access_size_pattern"] = str(stats.get("access_size_pattern", ("unknown", {})))
    
    return canonical_model


def project_dag(core_graph: nx.DiGraph, scale_params: dict) -> nx.DiGraph:
    """
    Project a workflow DAG at a desired scale using the canonical model
    
    Args:
        core_graph: The annotated core graph with rules
        scale_params: Dictionary with 'data_scale' and/or 'task_scale'
    
    Returns:
        Projected DAG with predicted properties
    """
    projected_dag = nx.DiGraph()
    
    print(f"\nProjecting DAG with scale parameters: {scale_params}")
    
    # Import the rules here to ensure they're available
    from rule_engine_auto import Rule1, Rule2, Rule3, Rule4, Rule5, Rule6, Rule7, Rule8
    
    # Map of rule_id to rule class
    rule_map = {
        "1": Rule1(),
        "2": Rule2(),
        "3": Rule3(),
        "4": Rule4(),
        "5": Rule5(),
        "6": Rule6(),
        "7": Rule7(),
        "8": Rule8()
    }
    
    for src, dst, edge_data in core_graph.edges(data=True):
        # Extract rule information
        rule_id = edge_data.get("rule_id", None)
        
        if rule_id is None:
            print(f"Warning: No rule_id for edge ({src}, {dst})")
            continue
        
        # Convert string rule_id to actual rule object
        if isinstance(rule_id, str):
            # Clean up the rule_id if needed (removing any non-digit characters)
            rule_id = ''.join(filter(str.isdigit, rule_id))
            
            if rule_id in rule_map:
                rule = rule_map[rule_id]
            else:
                print(f"Warning: Unknown rule_id {rule_id} for edge ({src}, {dst}), defaulting to Rule 8")
                rule = rule_map["8"]  # Default to empirical rule
        else:
            rule = edge_data.get("rule")
            if isinstance(rule, str):
                # If rule is a string representation, try to get the rule_id
                if "Rule" in rule:
                    rule_num = rule.split("Rule")[1].split(":")[0].strip()
                    if rule_num in rule_map:
                        rule = rule_map[rule_num]
                    else:
                        print(f"Warning: Could not parse rule from {rule}, defaulting to Rule 8")
                        rule = rule_map["8"]
                else:
                    print(f"Warning: Unknown rule format {rule}, defaulting to Rule 8")
                    rule = rule_map["8"]
        
        # Extract base metrics
        base_metrics = {
            EdgeAttrType.DATA_VOL: float(edge_data.get("observed_volumes", [1])[0]) if isinstance(edge_data.get("observed_volumes", [1]), list) else 1,
            EdgeAttrType.ACC_SIZE: float(edge_data.get("observed_access_sizes", [1])[0]) if isinstance(edge_data.get("observed_access_sizes", [1]), list) else 1,
            "accesses": 10  # Default value
        }
        
        # Apply rule to predict metrics
        predicted_metrics = rule.predict(scale_params, base_metrics)
        
        # Create projected edge
        projected_edge_data = {
            "rule_id": rule_id,
            "rule_name": getattr(rule, 'name', f"Rule {rule_id}"),
            "confidence": edge_data.get("rule_confidence", 0.5),
            EdgeAttrType.DATA_VOL: str(predicted_metrics[EdgeAttrType.DATA_VOL]),
            EdgeAttrType.ACC_SIZE: str(predicted_metrics[EdgeAttrType.ACC_SIZE])
        }
        
        projected_dag.add_edge(src, dst, **projected_edge_data)
        
        # Add node attributes
        if src not in projected_dag.nodes:
            type_hint = "file" if any(ext in src for ext in ('.txt', '.vcf', '.gz')) else "task"
            projected_dag.add_node(src, type=type_hint)
            
        if dst not in projected_dag.nodes:
            type_hint = "file" if any(ext in dst for ext in ('.txt', '.vcf', '.gz')) else "task"
            projected_dag.add_node(dst, type=type_hint)
    
    return projected_dag


def main():
    parser = argparse.ArgumentParser(description="Create canonical workflow model with automatic scaling detection")
    parser.add_argument("--data-instances", nargs='+', required=True,
                        help="Workflow instances with data scaling (2-3 files)")
    parser.add_argument("--task-instances", nargs='+', required=True,
                        help="Workflow instances with task scaling (2-3 files)")
    parser.add_argument("--output-data", default="canonical_model_data_scaling.graphml",
                        help="Output file for data scaling model")
    parser.add_argument("--output-task", default="canonical_model_task_scaling.graphml",
                        help="Output file for task scaling model")
    parser.add_argument("--project", action='store_true',
                        help="Project DAG at specific scale")
    parser.add_argument("--project-data-scale", type=float, default=2.0,
                        help="Data scaling factor for projection")
    parser.add_argument("--project-task-scale", type=float, default=2.0,
                        help="Task scaling factor for projection")
    
    args = parser.parse_args()
    
    print("=== FlowForecaster: Canonical Model Creation ===")
    print(f"Data instances: {len(args.data_instances)} files")
    print(f"Task instances: {len(args.task_instances)} files")
    
    # Process data scaling instances
    print("\n=== Processing Data Scaling Instances ===")
    data_compound_graphs, data_edge_stats = process_instances_for_scaling_type(
        args.data_instances, "data"
    )
    
    print("\n=== Inferring Rules for Data Scaling ===")
    data_edge_rules = infer_rules_for_scaling_type(data_edge_stats, "data")
    
    print("\n=== Creating Core Graph for Data Scaling ===")
    data_core_graph = create_canonical_model_with_rules(
        data_compound_graphs, data_edge_rules, "data"
    )
    
    # Process task scaling instances
    print("\n=== Processing Task Scaling Instances ===")
    task_compound_graphs, task_edge_stats = process_instances_for_scaling_type(
        args.task_instances, "task"
    )
    
    print("\n=== Inferring Rules for Task Scaling ===")
    task_edge_rules = infer_rules_for_scaling_type(task_edge_stats, "task")
    
    print("\n=== Creating Core Graph for Task Scaling ===")
    task_core_graph = create_canonical_model_with_rules(
        task_compound_graphs, task_edge_rules, "task"
    )
    
    # Save the core graphs
    print(f"\n=== Saving Results ===")
    print(f"Saving data scaling model to {args.output_data}")
    flatten_graph_for_graphml(data_core_graph)
    nx.write_graphml(data_core_graph, args.output_data)
    
    print(f"Saving task scaling model to {args.output_task}")
    flatten_graph_for_graphml(task_core_graph)
    nx.write_graphml(task_core_graph, args.output_task)
    
    # Visualize
    # show_dag(data_core_graph, msg="data_scaling_core_graph")
    # show_dag(task_core_graph, msg="task_scaling_core_graph")
    
    # Print summary
    print("\n=== Summary ===")
    print(f"Data scaling core graph: {data_core_graph.number_of_nodes()} nodes, "
          f"{data_core_graph.number_of_edges()} edges")
    print(f"Task scaling core graph: {task_core_graph.number_of_nodes()} nodes, "
          f"{task_core_graph.number_of_edges()} edges")
    
    # Optional: Project DAGs at specific scales
    if args.project:
        print("\n=== Projecting DAGs ===")
        
        # Project data scaling
        data_scale_params = {"data_scale": args.project_data_scale}
        data_projected = project_dag(data_core_graph, data_scale_params)
        data_proj_file = f"projected_data_scale_{args.project_data_scale}.graphml"
        nx.write_graphml(data_projected, data_proj_file)
        print(f"Saved data scaling projection to {data_proj_file}")
        
        # Project task scaling
        task_scale_params = {"task_scale": args.project_task_scale}
        task_projected = project_dag(task_core_graph, task_scale_params)
        task_proj_file = f"projected_task_scale_{args.project_task_scale}.graphml"
        nx.write_graphml(task_projected, task_proj_file)
        print(f"Saved task scaling projection to {task_proj_file}")
    
    print("\n=== Complete ===")


if __name__ == "__main__":
    main()