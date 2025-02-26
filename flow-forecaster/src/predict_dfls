import networkx as nx
import argparse
import parse_dfls

metric='volume'
stages = ['mProject', 'mBackground', 'mViewer']

def canonical_rule(g, u, v, metric, rule):
    if rule == 'r1':
        if g.has_edge(u, v):
            data = g[u][v][metric]
            return sum(data)/len(data)
        else:
            return None
    elif rule == 'r6':
        c_edges = g.in_edges(nbunch=v, data=True)
        c_edges_val = [x[metric][0] for u, v, x in c_edges]
        p_edges = g.out_edges(nbunch=v, data=True)
        p_edges_val = [x[metric][0] for u, v, x in p_edges]
        #print(u, v, c_edges_val, p_edges_val)
        if len(c_edges_val) > 0:
            return sum(c_edges_val)/len(c_edges_val)
        else:
            return None

    else:
        if g.has_edge(u, v):
            data = g[u][v][metric]
            #print(u, v, g[u][v])
            return sum(data)/len(data)
        else:
            return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compound_graph')
    parser.add_argument('--test_graph')
    parser.add_argument('--factor', type=float)
    args = parser.parse_args()

    if args.compound_graph is None:
        return
    m_G = nx.read_edgelist(args.compound_graph, create_using=nx.DiGraph)
    t_G = nx.read_edgelist(args.test_graph, create_using=nx.DiGraph)
    G = nx.DiGraph()
    for stage in stages:
        for u, v, data in m_G.in_edges(stage, data=True):
            for u2, v2, _d in t_G.edges(data=True):#u, v):
                uname = parse_dfls.nodename_abstract(u2)
                vname = parse_dfls.nodename_abstract(v2)
                if v != vname and v != uname:
                    #print(u,v,data)
                    continue

                # FIX to automate
                #print(u2, v2, _d, stage)
                if stage == 'mProject' or stage == 'mBackground':
                    rule = 'r1'
                elif (stage == 'mViewer') or (vname == 'mViewer'):
                    rule = 'r7'
                else:
                    rule = 'r7'

                predicted = canonical_rule(m_G, uname, vname, metric, rule)
                measured = t_G[u2][v2][metric]
                if measured == 0 or predicted == None:
                    #print(u,v, u2,v2)
                    continue
                #print(t_G[u2][v2], u2, v2)
                print ('{}->{}:{}/{}  (predicted / measured)'.format(u2, v2, predicted, measured ))
                if rule == 'r7':
                    acc = round(abs(1-(measured-(predicted*args.factor))/predicted)*100, 3)
                else:
                    acc = round(abs(1-(measured-predicted)/predicted)*100, 3)
                if G.has_edge(u2, v2) is False:
                    G.add_edge(u2, v2, accuracy=acc)
                    #G.edges[uname, vname].update({'accuracy':G[uname][vname]['accuracy'] + [acc]})

    res = { stage: [] for stage in stages }
    #for u, v, data in G.edges(data=True):
    G_merged = nx.DiGraph()
    for u, v, data in G.edges(data=True):
        uname = parse_dfls.nodename_abstract(u)
        vname = parse_dfls.nodename_abstract(v)
        if G_merged.has_edge(uname, vname) is False:
            G_merged.add_edge(uname, vname, accuracy=[data['accuracy']])
        else:
            acc = G_merged[uname][vname]['accuracy']
            #print(acc, uname, vname)
            G_merged.edges[uname, vname].update({'accuracy':acc + [data['accuracy']]})

    nx.write_edgelist(G_merged, f"{metric}_predicted_graph.edgelist", data=True)
    return

if __name__ == "__main__":
    main()
