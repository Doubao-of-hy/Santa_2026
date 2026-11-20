"""Rebuild two target branches from one funded target and a shared integer coordinate."""
import argparse,csv,json,random,subprocess
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from itertools import permutations
from math import gcd
from pathlib import Path

from run_source import ROOT
from elf import arithmetic,check,read_puzzles,read_submission,sha256,write_submission
from graph import active_graph,first_recipes
from gpu_join import cut_many
from parallel_solve import Helpers,compile_best


def reduced(a,b,c,d):
    g=gcd(gcd(abs(a),abs(b)),gcd(abs(c),abs(d)))
    if d<0:g=-g
    return a//g,b//g,c//g,d//g


class Arithmetic:
    def __init__(self,p,helpers):
        self.limit=p.limit;self.helpers=helpers;self.graph={};self.seeds=p.seeds

    def op(self,op,x,y):
        v=arithmetic(op,x,y)
        if v<1 or v>self.limit:raise ValueError("out of range")
        if v not in self.helpers.known and v not in self.graph:
            if v in (x,y):raise ValueError("unfunded identity")
            self.graph[v]=op,x,y
        return v

    def literal(self,v):
        if v in self.graph or v in self.helpers.known:return v
        opts=self.helpers.choices(v)
        if opts:
            self.graph.update(opts[0]);return v
        if v==1:return self.op("/",self.seeds[0],self.seeds[0])
        if v>256:raise ValueError("unfunded integer")
        self.literal(1);x=1
        for digit in bin(v)[3:]:
            x=self.op("+",x,x)
            if digit=="1":x=self.op("+",x,1)
        return x

    def scaled(self,x,k,d):
        common=gcd(abs(k),d);k//=common;d//=common
        if d>1:
            if x%d:raise ValueError("nonintegral scaled term")
            x=self.op("/",x,self.literal(d))
        if abs(k)>1:x=self.op("*",x,self.literal(abs(k)))
        return x if k>0 else -x

    def affine(self,x,h,form,goal,separate):
        a,b,c,d=form;den=d if separate else 1
        if (c%den) or (not separate and goal>self.limit//d):raise ValueError("denominator")
        signed=[]
        for v,k in ((x,a),(h,b)):
            if k:signed.append(self.scaled(v,k,den))
        if c:signed.append(self.literal(abs(c)//den)*(1 if c>0 else -1))
        while len(signed)>1:
            i,j=min(((i,j) for i in range(len(signed)) for j in range(i+1,len(signed))),
                    key=lambda index:abs(signed[index[0]]+signed[index[1]]))
            y=signed.pop(j);z=signed.pop(i);value=y+z
            if value:
                if y*z>0:self.op("+",abs(y),abs(z))
                else:self.op("-",max(abs(y),abs(z)),min(abs(y),abs(z)))
                signed.append(value)
        if not signed or signed[0]<=0:raise ValueError("nonpositive result")
        result=signed[0]
        if not separate and d>1:result=self.op("/",result,self.literal(d))
        if result!=goal:raise ValueError("incorrect coordinate")


def forms_for(p,coeff,e,x,y,z,helpers):
    kx,ky,kz=coeff
    known=helpers.known;one=helpers.one;choices={}
    scales=(1,2,3,4,5,6,8)
    shifts={0,1,-1,*p.seeds,*(-s for s in p.seeds)}
    for den in (1,2,3,4,5,6,8):
        for n in scales:
            if gcd(n,den)>1:continue
            for shift in shifts:
                delta=den*y-n*x-shift
                if not delta:continue
                for k in scales:
                    if delta%k:continue
                    h=abs(delta)//k;ks=k if delta>0 else -k
                    if h in (x,y,z) or h>p.limit:continue
                    f1=reduced(n,ks,shift,den)
                    f2=reduced(-(kx*den+ky*n),-ky*ks,den*e-ky*shift,kz*den)
                    def price(f):
                        a,b,c,d=f
                        return (int(abs(a)>1)+int(abs(b)>1)+int(d>1)+int(c!=0)+int(a!=0)
                                +.4*sum(v not in known and v>1 for v in (abs(a),abs(b),abs(c),d)))
                    cls=0 if h in known else (1 if h in one else 2)
                    rank=(cls,price(f1)+price(f2),h.bit_length())
                    key=h,f1,f2
                    choices[key]=rank
    buckets=[[],[],[]]
    for key,rank in choices.items():buckets[rank[0]].append((rank,key))
    for entries,limit in zip(buckets,(150,100,28)):
        for _,entry in sorted(entries)[:limit]:yield entry


def repair(p,tape,rules):
    best=tape;graph=active_graph(p,first_recipes(p,tape));stats=[0]*5;smallest_gap=None
    for rule in rules:
        targets=rule[:3];weights=(rule[3],rule[4],-rule[5]);error=rule[6]
        proposals=[]
        for keep_index in range(3):
            x=targets[keep_index];others=[j for j in range(3) if j!=keep_index]
            kept,paid=cut_many(p,graph,{targets[j] for j in others})
            if x not in paid and x not in p.seeds:continue
            budget=len(graph)-len(kept)
            if budget<3:continue
            helpers=Helpers(p,paid)
            seen=set()
            for ii,jj in permutations(others):
                y,z=targets[ii],targets[jj];ks=(weights[keep_index],weights[ii],weights[jj])
                for h,f1,f2 in forms_for(p,ks,error,x,y,z,helpers):
                    if not helpers.choices(h):continue
                    stats[0]+=1
                    for separate in (False,True):
                        ar=Arithmetic(p,helpers);ar.literal(h)
                        try:
                            ar.affine(x,h,f1,y,separate);ar.affine(x,h,f2,z,separate)
                        except (ValueError,ZeroDivisionError):continue
                        if y not in ar.graph or z not in ar.graph:continue
                        closures=[]
                        for target in (y,z):
                            used=set();stack=[target]
                            while stack:
                                value=stack.pop()
                                if value in used:continue
                                used.add(value)
                                if value in ar.graph:stack.extend(ar.graph[value][1:])
                            closures.append(used)
                        # Either final operation can stay intact when an earlier
                        # operation changes. Both reconstructed branches must
                        # genuinely use the common coordinate.
                        if any(h not in path for path in closures):continue
                        live={v:r for v,r in ar.graph.items() if any(v in path for path in closures)}
                        key=tuple(sorted(live.items()))
                        if key in seen:continue
                        seen.add(key)
                        stats[1]+=1
                        try:g=active_graph(p,graph|live)
                        except (ValueError,KeyError):continue
                        gap=len(g)-len(graph)
                        smallest_gap=gap if smallest_gap is None else min(gap,smallest_gap)
                        stats[4]+=int(gap==0)
                        if len(g)<len(best):proposals.append((len(g),g))
        stats[2]+=len(proposals)
        for _,g in sorted(proposals,key=lambda q:q[0])[:4]:
            program=compile_best(p,graph,g)
            if program is not None and len(program)<len(best):
                best=program;graph=active_graph(p,first_recipes(p,best));stats[3]+=1
    check(p,best)
    return p.id,best,stats,smallest_gap


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for s in ("puzzles","baseline","scanner","families","output"):ap.add_argument(s,type=Path)
    ap.add_argument("--jobs",type=int,default=3);a=ap.parse_args()
    ps=read_puzzles(a.puzzles);base=read_submission(a.baseline)
    family={r["id"]:r for r in csv.DictReader(a.families.open(encoding="utf-8-sig"))}
    selected=[p for p in ps if family[p.id]["assigned"]=="shared"]
    inp="".join(" ".join(map(str,("official",p.id,p.limit,len(p.seeds),len(p.targets),*p.seeds,*p.targets)))+"\n" for p in selected)
    native=subprocess.run([str(a.scanner.resolve()),"rules"],input=inp,text=True,capture_output=True,check=True)
    rules=defaultdict(list)
    for line in native.stdout.splitlines():
        fields=line.split()
        if fields[0]=="R":rules[fields[1]].append(tuple(map(int,fields[2:])))
    selected=[p for p in selected if rules[p.id]];gains={};totals=[0]*5;out={};gaps={}
    with ProcessPoolExecutor(a.jobs) as pool:
        tasks=[pool.submit(repair,p,base[p.id],rules[p.id]) for p in selected]
        for t in as_completed(tasks):
            k,v,c,gap=t.result();totals=[i+j for i,j in zip(totals,c)];out[k]=v;gaps[k]=gap
            if len(v)<len(base[k]):gains[k]=len(base[k])-len(v)
    write_submission(a.output,selected,out)
    meta={"puzzles_sha256":sha256(a.puzzles),"baseline_sha256":sha256(a.baseline),
          "repair_source_sha256":sha256(Path(__file__)),
          "scanner_sha256":sha256(a.scanner),"family_assignments_sha256":sha256(a.families),
          "selected":len(selected),"identities":sum(map(len,rules.values())),"gains":gains,
          "funded_coordinates":totals[0],"distinct_shared_coordinate_graphs":totals[1],
          "shorter_graphs":totals[2],"accepted":totals[3],"equal_length_graphs":totals[4],
          "best_gap_per_puzzle":dict(sorted(gaps.items())),"output_sha256":sha256(a.output)}
    a.output.with_suffix(".json").write_text(json.dumps(meta,indent=2),encoding="utf8")
    print(meta)

if __name__=="__main__":main()
