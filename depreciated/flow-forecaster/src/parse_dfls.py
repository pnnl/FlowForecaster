import yaml
import networkx as nx

def known_datanode_ext(node):
    ext_list = ['tar.gz']
    return node in ext_list

def nodename_abstract(node):
    node_type = 'task'
    if known_datanode_ext(node):
        node_type = 'data'
    if node_type == 'data':
        #chr1n-1-1251.tar.gz 
        return node
    else:
        #individuals_ID0000001
        return node.rsplit("_", 1)[0]

def main():
    dfls = ['36tasks_data']
    metric = 'volume'
    c_G = nx.DiGraph()

    for dfl in dfls:
        c_G = nx.DiGraph()
        fname = f'{dfl}/workflow_taskname.edgelist'
        d = nx.read_edgelist(fname, create_using=nx.DiGraph)
        for u, v, data in d.edges(data=True):
            print (u, v, data)
            uname = nodename_abstract(u)
            vname = nodename_abstract(v)
            if data[metric] == 0:
                continue
            if c_G.has_edge(uname, vname):
                odata = c_G.edges[uname, vname][metric]
                cnt = c_G.edges[uname, vname]['edge_count']
                c_G.edges[uname, vname].update({metric: odata + [data[metric]], 'edge_count': cnt + 1})
            else:
                c_G.add_edge(uname, vname,**{metric: [data[metric]], 'edge_count': 1})
            print(c_G.edges(data=True))
        nx.write_edgelist(c_G, f"{metric}_{dfl}_task_scaling_compound_graph.edgelist", data=True)

if __name__ == "__main__":
    main()
