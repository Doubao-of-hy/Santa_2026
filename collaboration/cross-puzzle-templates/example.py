"""Independently replay transferred recipes that exactly reach previously unseen official targets."""
import argparse,hashlib,json
from dataclasses import replace
from pathlib import Path
from evaluate import instantiate_lifted,decode,read_puzzles,compile_graph,check,first_recipes,active_graph,read_submission
from solvers.gpu.gpu_join import cut_many

def main():
    ap=argparse.ArgumentParser();ap.add_argument('puzzles',type=Path);ap.add_argument('library',type=Path)
    ap.add_argument('exe',type=Path);ap.add_argument('independent',type=Path);ap.add_argument('out',type=Path)
    a=ap.parse_args();book=json.loads((a.library/'library.json').read_bytes())
    p=next(p for p in read_puzzles(a.puzzles) if p.id=='scored_0199')
    parent=read_submission(a.independent)[p.id];old=first_recipes(p,parent)
    lib=book['vocabulary']['frequent']
    matches,stats=instantiate_lifted(p,a.library/'frequent.txt',a.exe.resolve(),set(p.targets));rows=[]
    for t,info in sorted(matches.items()):
        ix,binding,_=info;patch=decode(p,t,info,lib)
        solo=replace(p,targets=(t,));program=compile_graph(solo,patch,recompute=True)
        assert check(solo,program)==len(program)
        other,free=cut_many(p,old,{t})
        filtered={x:e for x,e in patch.items() if x not in free}
        changed=active_graph(p,old|filtered)
        rows.append({'target_index_zero_based':p.targets.index(t),'template_index_zero_based':ix,
                     'practice_source':lib[ix]['source_ids'],'official_role_binding':binding,
                     'standalone_instructions':len(program),'original_single_target_cone':len(active_graph(solo,old)),
                     'original_exclusive_operations':len(old)-len(other),'whole_parent':len(parent),
                     'graph_with_replacement':len(changed),'program':program})
    assert len(rows)==3
    a.out.write_text(json.dumps({'id':p.id,'arm':'one paid extra seed operand, frequent fragments','rows':rows},indent=2)+'\n',encoding='utf8')
    print([(r['practice_source'],r['target_index_zero_based'],r['standalone_instructions'],r['original_exclusive_operations'],r['graph_with_replacement']) for r in rows])

if __name__=='__main__':main()
