
length = len(generations)
level = 0

# Found the boundary
task_collection = get_first_iteration_tasks()

while level < length - 1:
    heads = generations[level]
    ends = generations[level + 1]

    # Process tasks (ends)
    compound_tasks_map = {}
    for task in ends:
        task_prefix = get_task_prefix(task)
        if task_prefix in task_map:
            compound_tasks_map[task_prefix].append(task)
        else:
            compound_tasks_map[task_prefix] = [task]

    # Process files (heads)
    compound_files_map = {}
    for task_prefix in compound_files_map:
        compound_files_map[task_prefix] = set()
    # traverse edges
    for file in heads:
        for task in G.successors(file):
            # edge (file, task)
            task_prefix = get_task_prefix(task)
            compound_files_map[task_prefix].add(file)


    # Generate compound output file vertex from the ends

    # Generate compound edge from compound task to compound file
