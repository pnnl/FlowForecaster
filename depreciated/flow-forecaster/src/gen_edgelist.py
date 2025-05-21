import yaml
import glob
import networkx as nx
import os
import pandas as pd

G = nx.DiGraph()
def parse_stat(fpath, rw='r'):
    stat_path = glob.glob(fpath)
    print(stat_path)
    df = pd.read_csv(stat_path[0], sep=' ', skiprows=1, header=None, names=['bidx','cnt','size'])
    skiprows = df[df['cnt']=='Block'].index
    if skiprows.dtype == 'object':
        df=df.apply(pd.to_numeric, errors='coerce')
        df=df.dropna()
    if df.empty:
        return 0, 0, 0
    #if df['size'].dtype == 'object':
    if len(skiprows) > 0:
        last_index = skiprows[-1]
        df = pd.read_csv(stat_path[0], sep=' ', skiprows=last_index + 2, header=None, names=['bidx','cnt','size'])
        print(last_index, stat_path)
        if df.empty:
            return 0, 0, 0
    vol = (df['size'] * df['cnt']).sum()
    cnt = df['cnt'].sum()
    size = df['size'].mean() or 0
    return (vol, cnt, size)

with open('montage-workflow.yml') as f:
    data = yaml.safe_load(f)
    for idx, job in enumerate(data['jobs']):
        dnodes = list(set([ os.path.basename(x.rsplit("_",3)[0]) for x in glob.glob(f"task_{idx}/*_r_stat")]))
        #print(dnodes)
        for dnode in dnodes:
            vol, cnt, size = parse_stat(os.path.join(f"task_{idx}", dnode + "*_r_stat"))
            G.add_edge(dnode, f'{job["name"]}_{job["id"]}', volume=vol, count=cnt, size=size)
            vol, cnt, size = parse_stat(os.path.join(f"task_{idx}", dnode + "*_w_stat"), 'w')
            #G.add_edge(f'task_{idx}', dnode, volume=vol, count=cnt, avg_size=size)
            G.add_edge(f'{job["name"]}_{job["id"]}', dnode, volume=vol, count=cnt, size=size)
        #for line in nx.generate_edgelist(G, data=True):
        #    print(line)

    nx.write_edgelist(G, 'workflow_taskname.edgelist', data=True)
