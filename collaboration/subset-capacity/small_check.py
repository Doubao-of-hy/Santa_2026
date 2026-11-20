"""Exhaust small positive-integer machines and compare projected capacities to complete enumeration."""
import itertools,json
from collections import deque
from pathlib import Path
from verify import outcomes,solve_pair,envelope,choose_targets,capacity

HERE=Path(__file__).resolve().parent

def possibilities(seeds,cap):
    start=frozenset(seeds);depth={start:0};queue=deque([start])
    while queue:
        state=queue.popleft()
        for a,b in itertools.combinations_with_replacement(state,2):
            for x in outcomes(a,b,cap)-state:
                child=state|{x}
                if child not in depth:depth[child]=depth[state]+1;queue.append(child)
    return depth

def main():
    counts={'checked_operand_pairs':0,'seed_target_instances':0,'finite_optima':0,'subsets':0,'helper_budgets':0,'strict_exclusions':0}
    gold=[]
    for cap in range(3,9):
        universe=tuple(range(1,cap+1))
        for x,y in itertools.combinations(universe,2):
            brute={(b,a) for a,b in itertools.combinations(universe,2) if {x,y}<=outcomes(a,b,cap)}
            assert brute==solve_pair(x,y,cap)
            counts['checked_operand_pairs']+=1
        for nseed in [1,2]:
            for seeds in itertools.combinations(universe,nseed):
                dist=possibilities(seeds,cap)
                for ng in [1,2,3]:
                    for g in itertools.combinations(universe,ng):
                        goals=set(g);M=len(goals-set(seeds))
                        if not M:continue
                        counts['seed_target_instances']+=1
                        opt=min((d for known,d in dist.items() if goals<=known),default=None)
                        if opt is None:continue
                        counts['finite_optima']+=1
                        for k in (0,1,2):
                            allowed,prior=envelope(set(seeds),goals,cap,k)
                            if k and not goals-prior:continue
                            free=allowed|goals
                            u=choose_targets((allowed,free),goals,cap)
                            for n in range(1,len(u)+1):
                                for selected in itertools.combinations(sorted(u),n):
                                    counts['subsets']+=1
                                    for h in range(3):
                                        counts['helper_budgets']+=1
                                        scalar,_=capacity(allowed,goals,set(selected),cap,h)
                                        brute,_=capacity(allowed,goals,set(selected),cap,h,True)
                                        assert scalar==brute
                                        if scalar<n:
                                            assert M+k+h+1<=opt,(seeds,g,k,h,selected,opt)
                                            counts['strict_exclusions']+=1
                                            if (len(gold)<3 and n<len(u) and opt>=4 and h==0 and k>=1 and all(x['cap']!=cap for x in gold)):
                                                gold.append({'cap':cap,'seeds':seeds,'targets':g,'counted':selected,'first_helpers':k,'remaining_budget_excluded':h,'projected_lower':M+k+h+1,'exact_optimum':opt})
    available,prior=envelope({5},{3,7},7,1)
    assert 3 in choose_targets((available,available|{3,7}),{3,7},7)
    assert capacity(available,{3,7},{3},7,0)[0]==0
    assert min(n for state,n in possibilities({5},7).items() if {3,7}<=state)==4
    base={2};goals={4,8}
    assert 8 not in choose_targets((base,base|goals),goals,8)
    assert 8 in choose_targets((base,base|{8}),{8},8)
    assert min(n for state,n in possibilities({2},8).items() if goals<=state)==2
    out={'negative_control':{'reason':'Dropping uncounted target 4 from the operand bank would incorrectly label target 8 unsupported. Legal tape: 4=2+2, 8=4+4. No non-target helper needed.','seeds':[2],'targets':[4,8],'counted':[8],'optimum':2},'counts':counts,'examples':gold,'register_relaxation':'All computed positive values stay available; BFS includes all legal pairs and operations within cap.'}
    (HERE/'small-check.json').write_text(json.dumps(out,indent=1)+'\n',encoding='utf8');print(out)
if __name__=='__main__':main()
