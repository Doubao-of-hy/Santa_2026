"""CP-SAT synthesis of one shared straight-line program over several residue fields."""
from collections import Counter
from functools import lru_cache
import time
from instances import ROOT
from ortools.sat.python import cp_model

OPS="+-*/"

@lru_cache(maxsize=None)
def residue_table(p):
    return ([(op,x,y,z) for x in range(p) for y in range(p)
             for op,z in ((0,(x+y)%p),(1,(x-y)%p),(2,(x*y)%p))]
            +[(3,(q*y)%p,y,q) for q in range(p) for y in range(p)])

def iff(model,var,value,name):
    b=model.new_bool_var(name)
    model.add(var==value).only_enforce_if(b)
    model.add(var!=value).only_enforce_if(b.Not())
    return b

def build(anchors,roots,length,primes):
    m=cp_model.CpModel();size=len(anchors);ops=[];left=[];right=[]
    root_at=m.new_int_var(1,length-2,"earlier_output")
    swapped=m.new_bool_var("swap_roots")
    witness=m.new_int_var(0,length-3,"shared_helper")
    m.add(witness<root_at)
    feature=[0]*size
    for k in range(length):
        op=m.new_int_var(0,3,f"op{k}");a=m.new_int_var(0,size+k-1,f"a{k}");b=m.new_int_var(0,size+k-1,f"b{k}")
        commutes=m.new_bool_var(f"comm{k}")
        m.add_allowed_assignments([op,commutes],[(0,1),(1,0),(2,1),(3,0)])
        m.add(a<=b).only_enforce_if(commutes)
        via_a=m.new_bool_var(f"reach_a{k}");via_b=m.new_bool_var(f"reach_b{k}")
        m.add_element(a,feature,via_a);m.add_element(b,feature,via_b)
        shared=m.new_bool_var(f"reach{k}")
        m.add_max_equality(shared,[via_a,via_b,iff(m,witness,k,f"is_helper{k}")])
        feature.append(shared);ops.append(op);left.append(a);right.append(b)
    m.add(feature[-1]==1)
    m.add_element(root_at,feature[size:],1)
    for k in range(length-1):
        uses=[iff(m,root_at,k,f"is_root{k}")]
        for j in range(k+1,length):
            uses+=[iff(m,left[j],size+k,f"use_l{j}_{k}"),iff(m,right[j],size+k,f"use_r{j}_{k}")]
        # In an acyclic program this guarantees that every instruction feeds an output.
        m.add_bool_or(uses)
    for p in primes:
        slots=[v%p for v in anchors]
        for k in range(length):
            x=m.new_int_var(0,p-1,f"mod{p}_left{k}");y=m.new_int_var(0,p-1,f"mod{p}_right{k}");v=m.new_int_var(0,p-1,f"mod{p}_out{k}")
            m.add_element(left[k],slots,x);m.add_element(right[k],slots,y)
            m.add_allowed_assignments([ops[k],x,y,v],residue_table(p));slots.append(v)
        earlier=m.new_int_var(0,p-1,f"mod{p}_earlier")
        m.add_element(root_at,slots[size:],earlier)
        for flag,vals in [(swapped.Not(),roots),(swapped,roots[::-1])]:
            m.add(earlier==vals[0]%p).only_enforce_if(flag)
            m.add(slots[-1]==vals[1]%p).only_enforce_if(flag)
    structure=[v for triple in zip(ops,left,right) for v in triple]+[root_at,swapped]
    return m,structure

def execute(anchors,roots,cap,shape):
    pos,swap=shape[-2:];slots=list(anchors);edges=[];ancestry=[0]*len(anchors)
    for k in range((len(shape)-2)//3):
        op,a,b=shape[3*k:3*k+3];x=slots[a];y=slots[b]
        if op==0:v=x+y
        elif op==1:v=x-y
        elif op==2:v=x*y
        else:
            if y<=0 or x%y:return None,"nonintegral"
            v=x//y
        if v<1:return None,"nonpositive"
        if v>cap:return None,"over_limit"
        slots.append(v);edges.append((v,OPS[op],x,y))
        ancestry.append(ancestry[a]|ancestry[b]|(1<<k))
    expected=tuple(reversed(roots)) if swap else tuple(roots)
    if (slots[len(anchors)+pos],slots[-1])!=expected:return None,"wrong_roots"
    first=ancestry[len(anchors)+pos];last=ancestry[-1]
    assert (first|last)==(1<<len(edges))-1 and (first&last)&~(1<<pos)
    return edges,"exact"

class Batch(cp_model.CpSolverSolutionCallback):
    def __init__(self,structure,banned,anchors,roots,cap,accept,deadline):
        super().__init__();self.structure=structure;self.banned=banned;self.anchors=anchors;self.roots=roots
        self.cap=cap;self.accept=accept;self.deadline=deadline;self.batch=set();self.status=Counter();self.winner=None
    def on_solution_callback(self):
        if time.monotonic()>=self.deadline:
            self.stop_search();return
        shape=tuple(self.value(v) for v in self.structure)
        if shape in self.banned or shape in self.batch:
            self.status["duplicate_modular_witness"]+=1
            if self.status["duplicate_modular_witness"]>=24:self.stop_search()
            return
        self.batch.add(shape)
        circuit,reason=execute(self.anchors,self.roots,self.cap,shape)
        self.status[reason]+=1
        if circuit is not None:
            result=self.accept(circuit)
            if result is not None:
                self.winner=(shape,result)
                self.stop_search();return
            self.status["no_physical_gain"]+=1
        if len(self.batch)>=64:self.stop_search()

def search(anchors,roots,cap,length,primes,seconds,accept,forced=None):
    start=time.monotonic();deadline=start+seconds
    model,shape=build(anchors,roots,length,primes)
    if forced is not None:
        for v,n in zip(shape,forced,strict=True):model.add(v==n)
    banned=set();stats=Counter();statuses=[];winner=None
    first_ready=time.monotonic()
    while time.monotonic()<deadline:
        solver=cp_model.CpSolver()
        solver.parameters.max_time_in_seconds=max(.005,deadline-time.monotonic())
        solver.parameters.num_search_workers=1;solver.parameters.random_seed=271828
        solver.parameters.enumerate_all_solutions=True;solver.parameters.linearization_level=0
        solver.parameters.symmetry_level=0
        callback=Batch(shape,banned,anchors,roots,cap,accept,deadline)
        status=solver.solve(model,callback);statuses.append(solver.status_name(status))
        stats.update(callback.status)
        if callback.batch:
            # Ban every assignment to the shared shape variables, including every
            # 0/0 residue completion, not just the modular witness in this batch.
            model.add_forbidden_assignments(shape,sorted(callback.batch));banned.update(callback.batch)
        if callback.winner:
            winner=callback.winner;break
        if status in (cp_model.INFEASIBLE,cp_model.OPTIMAL) or not callback.batch:break
    return winner,{"seconds":round(time.monotonic()-start,5),"model_seconds":round(first_ready-start,5),
                   "solver_statuses":statuses,"topologies_checked":len(banned),"outcomes":dict(stats),
                   "exhausted":bool(statuses and statuses[-1] in ("OPTIMAL","INFEASIBLE") and winner is None)}
