"""Positive controls with translated clusters and deliberately suboptimal but legal parents."""
from pathlib import Path
from itertools import combinations
import argparse,json,random
from ruler import run
from elf import Puzzle,check
from graph import compile_graph

def example(seed):
    rng=random.Random(248613+seed);factor=7919
    large=rng.sample(range(68000000,87000000),4)
    offsets=[13,17,23,29,37,43,59]
    seeds=(1,factor,*offsets,*large);g={};targets=[]
    for j,a in enumerate(large):
        up=a+1;g[up]='+',a,1
        older=up*factor;g[older]='*',up,factor
        for d in rng.sample(offsets,3):
            rest=factor-d;g[rest]='-',factor,d
            t=a*factor+d;g[t]='-',older,rest;targets.append(t)
    p=Puzzle('planted_'+str(seed).zfill(4),seeds,tuple(sorted(targets)),10**14)
    parent=compile_graph(p,g,attempts=3,recompute=True)
    check(p,parent)
    return p,parent

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('out',type=Path);ap.add_argument('--n',type=int,default=8);a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    for i in range(a.n):
        p,t=example(i);run(p,t,a.out)
