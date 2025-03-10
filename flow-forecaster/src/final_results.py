import networkx as nx
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-i")
args = parser.parse_args()

G = nx.read_edgelist(args.i, create_using=nx.DiGraph)
res = {'mProject': None,
'mBackground': None, 
'mViewer': None }
for u, v, data in G.edges(data=True):
    m_acc = data['accuracy']
    stage_name = 'mProject'
    if stage_name in [u, v]:
        avg_acc = sum(m_acc)/len(m_acc)
        if res[stage_name] == None:
            res[stage_name] = avg_acc
        else:
            res[stage_name] = (res[stage_name] + avg_acc )/2
    stage_name = 'mBackground'
    if stage_name in [u, v]:
        avg_acc = sum(m_acc)/len(m_acc)
        if res[stage_name] == None:
            res[stage_name] = avg_acc
        else:
            res[stage_name] = (res[stage_name] + avg_acc )/2
    stage_name = 'mViewer'
    if stage_name in [u, v]:
        avg_acc = sum(m_acc)/len(m_acc)
        if res[stage_name] == None:
            res[stage_name] = avg_acc
        else:
            res[stage_name] = (res[stage_name] + avg_acc )/2




print (res)

