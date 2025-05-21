import yaml
import os

symlink_f = { }
def transformation_catalog(tcatalog):

    tasks_info = {}
    '''with open("transformations.yml") as f:
    tasks = yaml.safe_load(f)
    for t in tcatalog['transformations']:
    '''
    for t in tcatalog['transformations']:
        tasks_info[t['name']] = t['sites'][0]['pfn']
    return tasks_info

def replica_catalog(rcatalog):
    replica_info = {}
    for r in rcatalog['replicas']:
        replica_info[r['lfn']] = r['pfns'][0]['pfn']
    return replica_info

def download(args, repl):
    res = []
    for arg in args:
        if arg in repl and 'http://' == repl[arg][:7]:
            res.append(f"wget '{repl[arg]}' -O {arg}")
        if arg in repl and 'file://' == repl[arg][:7]:
            #print(f"ln -s '{repl[arg][7:]}' -O {arg}")
            res.append(f"ln -s '{repl[arg][7:]}' {arg}")
    return res

def replace_args(args, syms=symlink_f):
    res = []
    for arg in args:
        if arg in syms:
            res.append('ln -sf ' + syms[arg] + f' {arg}')
        else:
            arg_path = os.path.join(os.getcwd(), arg)
            if os.path.exists(arg_path):
                res.append('ln -sf ' + arg_path + f' {arg}')
    return list(set(res))

def get_output_paths(uses, outputs, abspath):
    for use in uses:
        if use['type'] == 'output':
            outputs[use['lfn']] = os.path.join(abspath, use['lfn'])

def inputs_to_args(uses):
    res = []
    for use in uses:
        if use['type'] == 'input':
            res.append(use['lfn'])
    return res

with open("montage-workflow.yml") as f:
    data = yaml.safe_load(f)
    preload = 'LD_PRELOAD=/qfs/projects/oddite/leeh736/datalife/lib/libmonitor.so '
    base_path = os.getcwd()
    outputs = {}
    inputs = {}
    tasks_info = transformation_catalog(data['transformationCatalog'])
    replica_info = replica_catalog(data['replicaCatalog'])
    for idx, job in enumerate(data['jobs']):
        print(f"mkdir -p task_{idx};cd task_{idx};")
        print(";".join(replace_args(job['arguments'], tasks_info)))
        print(";".join(replace_args(inputs_to_args(job['uses']), outputs)))
        print(";".join(replace_args(job['arguments'], outputs)))
        print(";".join(download(job['arguments'], replica_info)))
        print(tasks_info[job['name']], ' '.join(job['arguments']))
        print(preload + tasks_info[job['name']], ' '.join(job['arguments']))
        get_output_paths(job['uses'], outputs, f'{base_path}/task_{idx}')
        print(f"cd -")
