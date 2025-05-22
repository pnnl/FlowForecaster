import networkx as nx
import argparse
import parse_dfls
import difflib

metric='count'
stages = ['individuals', 'individuals_merge', 'frequency', 'mutation_overlap']

def num_sim(n1, n2):
    """ calculates a similarity score between 2 numbers """
    return 1 - abs(n1 - n2) / (n1 + n2)

def similar_filename(a, b):
    return difflib.SequenceMatcher(a=a, b=b).ratio() >= 0.5

def canonical_rule(g, u, v, metric, rule, factor=1):
    if rule == 'r1':
        if g.has_edge(u, v):
            data = g[u][v][metric]
            return sum(data)/len(data)
        else:
            return None
    elif rule == 'r2':
        if g.has_edge(u, v):
            data = g[u][v][metric]
            return sum(data)/len(data)*factor
        else:
            return None

    elif rule == 'r6':
        c_edges = g.in_edges(nbunch=v, data=True)
        c_edges_val = [x[metric][0] for u, v, x in c_edges]
        p_edges = g.out_edges(nbunch=v, data=True)
        p_edges_val = [x[metric][0] for u, v, x in p_edges]
        print("$"*10, u, v, c_edges_val, p_edges_val, p_edges)
        if len(c_edges_val) > 0:
            print(sum(c_edges_val)/len(c_edges_val)*factor)
            return (sum(c_edges_val)/len(c_edges_val)*factor)
        else:
            return None
    elif rule == 'r7':
        if g.has_edge(u, v):
            data = g[u][v][metric]
            #print(u, v, g[u][v])
            return sum(data)/len(data)*factor
    else:
        if g.has_edge(u, v):
            data = g[u][v][metric]
            #print(u, v, g[u][v])
            #return sum(data)/len(data)*factor
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
        # in-edges, data-consumer
        for u, v, data in m_G.in_edges(stage, data=True):
            print("="*29,u,v)
            for u2, v2, _d in t_G.edges(data=True):#u, v):
                #print("0"*29,u2,v2)
                uname = parse_dfls.nodename_abstract(u2)
                vname = parse_dfls.nodename_abstract(v2)
                if v != vname and v != uname:
                    #print(u,v,data)
                    continue
                if similar_filename(u, uname) is False:
                    #print(f"similarity fail, {u}, {uname}, {similar_filename(u, uname)}")
                    continue
                print("-"*28, uname, vname, stage)

                # FIX to automate
                #print(u2, v2, _d, stage)
                if stage == 'individuals':
                    rules = ['r1', 'r2', 'r7']
                elif (stage == 'individuals_merge') or (vname == 'individuals_merge'):
                    rules = ['r6']
                elif (stage == 'mutation_overlap') or (vname == 'mutation_overlap') \
                        or (stage == 'frequency') or (vname == 'frequency'):
                    rules = ['r7', 'r7-1']
                else:
                    rules = ['r7']

                accs = []
                for rule in rules:
                    predicted = canonical_rule(m_G, uname, vname, metric, rule, args.factor)
                    if predicted == None:
                        print(f"*!@# {rule}, predicted None")
                        predicted = canonical_rule(m_G, u, v, metric, rule, args.factor)
                    measured = t_G[u2][v2][metric]
                    if measured == 0 or predicted == None:
                        print("+"*29,u,v, u2,v2, measured, predicted)
                        break
                    #acc = round(abs(1-(measured-predicted)/predicted)*100, 3)
                    print(measured, predicted)
                    measured=measured[0]
                    acc = round(num_sim(measured, predicted) * 100, 3)
                    accs.append([measured, predicted, acc])
                if measured == 0 or predicted == None:
                    print("aerljkwr measured zero or predicted is none")
                    continue
                #print(t_G[u2][v2], u2, v2)
                #print(accs)
                res = min(accs, key=lambda x:abs(x[2]-100))
                measured, predicted, acc = res
                print ('{}->{}:{}/{}  (predicted / measured)'.format(u2, v2, predicted, measured ))
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
