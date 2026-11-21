from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import csv,json,sys
from instances import HERE,ROOT,case,active_graph,first_recipes,cut_many,read_submission,read_puzzles,sha256
from synthesis import search,execute
from elf import Puzzle,check,score,write_submission
from solvers.gpu.gpu_schedule import schedule_like
from graph import compile_graph
from checkpoint import independent_score

def installer(p,original,record):
    g=active_graph(p,first_recipes(p,original))
    surviving,free=cut_many(p,g,set(record["roots"]))
    protected=set(free)|set(p.seeds)
    def physical(circuit):
        graph=surviving.copy();known=protected.copy()
        for value,op,left,right in circuit:
            if value not in known:
                graph[value]=(op,left,right);known.add(value)
        try: actual=active_graph(p,graph)
        except (KeyError,ValueError):return None
        if len(actual)>=len(original):return None
        warm=schedule_like(p,original,actual)
        options=[t for t in (warm,compile_graph(p,actual,attempts=4,schedule_width=3,recompute=True)) if t is not None]
        if not options:return None
        best=min(options,key=len);check(p,best)
        return best if len(best)<len(original) else None
    return physical

def one(arg):
    p,original,problem,arm=arg
    rec={"id":p.id,"arm":arm,"before":len(original),"eligible":problem is not None,"trials":[]}
    if not problem:
        rec["after"]=len(original)
        return rec,None
    best=original
    for length in problem["strict_lengths"]:
        result,log=search(problem["anchors"],problem["roots"],p.limit,length,[5] if arm=="single" else [5,7,11],2.5,installer(p,original,problem))
        log["length"]=length
        if result:
            shape,tape=result
            log["witness_shape"]=shape;log["physical_instructions"]=len(tape)
            if len(tape)<len(best):best=tape
        rec["trials"].append(log)
    rec["after"]=len(best)
    return rec,(best if len(best)<len(original) else None)

def controls():
    p=Puzzle("synthetic_shared",(11,13,17),(37,41),1000,8)
    base=(("+",1,1,3),("+",0,3,4),("+",0,2,5),("+",1,5,6));assert check(p,base)==4
    record={"roots":[37,41],"anchors":[11,13,17]}
    output={}
    for tag,primes in [("single",[5]),("multi",[5,7,11])]:
        planted,log=search(record["anchors"],record["roots"],p.limit,3,primes,2.5,installer(p,base,record))
        assert planted and check(p,planted[1])==3,(tag,log)
        zero_shape=(3,0,1,0,2,3,2,2,3,1,0)
        division,dlog=search([10,5,7],[9,14],1000,3,primes,2.5,lambda c:c,forced=zero_shape)
        assert division and execute([10,5,7],[9,14],1000,division[0])[1]=="exact"
        false,flog=search([10,5,7],[394,399],1000,3,primes,2.5,lambda c:c,forced=zero_shape)
        assert false is None and flog["outcomes"].get("wrong_roots")==1
        output[tag]={"shared_4_to_3":{"shape":planted[0],"program":planted[1],"trace":log},"division_10_over_5":{"shape":division[0],"trace":dlog},"modular_collision":flog}
    return output
