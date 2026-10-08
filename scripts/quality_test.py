"""Behavioral regression: local edits, topology, visual evidence and stale-plan guards."""
import argparse,copy,json,subprocess,sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from vectorize import load_prepared,palette_id,plan_regions
from region_cleanup import clean_regions
from stroke_replay import chains,make_lines
from svg_compat import load_svg
from version import VERSION

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='img2svg '+VERSION)
    p.add_argument('--work',required=True);a=p.parse_args()
    work=Path(a.work).resolve();work.mkdir(parents=True,exist_ok=True);scripts=Path(__file__).resolve().parent;passed=[]
    def run(script,*args,expected=0):
        result=subprocess.run([sys.executable,str(scripts/script),*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='replace')
        assert result.returncode==expected,result.stdout+'\n'+result.stderr
        return result
    w,h=128,96;labels=np.ones((h,w),np.uint16);alpha=np.full((h,w),255,np.uint8)
    palette=np.array([[255,250,240],[110,180,120],[113,182,122],[45,50,48],[252,225,150]],np.uint8)
    labels[20,20]=2;labels[20,90]=2;labels[10,63]=2;labels[30,30]=4;labels[50,10:100]=3
    alpha[35,35]=128;labels[35,35]=2;alpha[0,0]=0
    plan={'coordinate_size':[w,h],'palette_fingerprint':palette_id(palette),'default':{'id':'right','base':'#6eb478'},'roles':{'ink':[3],'highlight':[4]},'regions':[{'id':'left','base':'#6eb478','polygon':[[0,0],[63,0],[63,95],[0,95]],'cleanup':{'enabled':True,'max_area':3,'max_rgb_distance':10}}],'checkpoints':[{'id':'small-marks','box':[5,5,60,55]}]}
    np.savez_compressed(work/'prepared.npz',labels=labels,palette=palette,alpha=alpha)
    Image.fromarray(np.dstack([palette[labels],alpha])).save(work/'reference.png')
    regions,mapping=plan_regions(plan,labels)
    clean,reports=clean_regions(labels,palette,alpha,mapping,regions,plan['roles'])
    assert clean[20,20]==1,'Confirmed low-contrast island was not merged'
    assert np.array_equal(clean[mapping==0],labels[mapping==0]),'Other region was modified'
    assert clean[30,30]==4 and np.array_equal(clean[50],labels[50]),'Highlight or thin ink lost'
    assert clean[35,35]==2 and clean[10,63]==2,'Alpha/ownership boundary was crossed'
    passed+=['local_cleanup','other_region_unchanged','ink_and_highlight_protected','alpha_and_boundary_protected']
    off=copy.deepcopy(regions);off[1].pop('cleanup')
    unchanged,_=clean_regions(labels,palette,alpha,mapping,off,plan['roles']);assert np.array_equal(unchanged,labels)
    passed.append('faithful_default_no_cleanup')
    bad=copy.deepcopy(plan);bad['palette_fingerprint']='stale'
    try:load_prepared(work,bad)
    except ValueError as e:assert 'Palette changed' in str(e)
    else:raise AssertionError('Stale palette was accepted')
    passed.append('stale_palette_rejected')
    revised=copy.deepcopy(plan);revised['assignments']=[{'region':'right','polygon':[[15,15],[25,15],[25,25],[15,25]],'only_from':['left']}]
    _,reassigned=plan_regions(revised,labels);changed=mapping!=reassigned
    assert changed[20,20] and int(changed.sum())==121
    passed.append('local_ownership_override')
    cross=np.zeros((h,w),np.uint8);cross[48,10:118]=1;cross[10:86,64]=1
    paths,_=chains(cross,np.zeros_like(mapping),4)
    assert len(paths)==2 and sum(len(s)-1 for s in paths)==int(cross.sum())-1,'Junction did not preserve two continuous branches'
    split=mapping.copy();paths_split,_=chains(cross,split,4)
    for seq in paths_split:assert len({int(split[s//w,s%w]) for s in seq})==1,'Replay crossed semantic boundary'
    passed+=['crossing_stroke_continuity','replay_ownership_boundary']
    curved=np.zeros((h,w),np.uint8)
    xy=np.array([[x,round(40+12*np.sin(x/22))] for x in range(10,118)],np.int32)
    cv2.polylines(curved,[xy],False,1,2)
    make_lines(curved,np.zeros_like(mapping),[{'id':'curve'}],w,h,work/'curve.svg')
    assert any('C' in n.get('d','') for n in load_svg(work/'curve.svg')),'No supported Bézier generated'
    passed.append('supported_smooth_replay')
    (work/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
    run('vectorize.py','trace','--work',work,'--plan',work/'plan.json','--output',work/'illustration.svg','--line-art',work/'line-art.svg')
    run('visual_review.py','inspect',work/'reference.png','--output',work/'inspection','--tile-size',128)
    run('visual_review.py','plan',work/'reference.png','--work',work,'--plan',work/'plan.json','--output',work/'plan-review')
    run('visual_review.py','compare',work/'reference.png','--svg',work/'illustration.svg','--plan',work/'plan.json','--output',work/'comparison')
    result=json.loads((work/'comparison/comparison.json').read_text(encoding='utf-8'))
    assert result['quality_pass'] is None and result['crops'][0]['id']=='small-marks'
    assert Image.open(work/'plan-review/regions-full.png').size==(w,h)
    run('visual_review.py','audit','--review',work/'comparison/review-template.json','--comparison',work/'comparison/comparison.json','--svg',work/'illustration.svg',expected=2)
    passed+=['visual_evidence_generation','critical_crops','no_automatic_visual_pass','pending_review_rejected']
    # Pencil changes must never change the finished pigment geometry.
    run('vectorize.py','trace','--work',work,'--plan',work/'plan.json','--output',work/'legacy-final.svg','--line-art',work/'legacy-line.svg','--pencil-mode','legacy')
    assert (work/'legacy-final.svg').read_bytes()==(work/'illustration.svg').read_bytes()
    passed.append('replay_mode_preserves_final_art')
    assert result['toolkit_version']==VERSION and json.loads((work/'trace-report.json').read_text(encoding='utf-8'))['toolkit_version']==VERSION
    passed.append('version_in_reports')
    # Palette merge: tombstone slot keeps indices stable; new fingerprint rejects stale plans.
    mwork=work/'merge-case';mwork.mkdir()
    mp=np.array([[250,245,235],[110,180,120],[210,80,60],[45,50,48],[252,225,150]],np.uint8)
    ml=np.full((h,w),1,np.uint16);ml[48:,:]=2;ml[30,30]=4;ml[40,40]=3
    ma=np.full((h,w),255,np.uint8)
    np.savez_compressed(mwork/'prepared.npz',labels=ml,palette=mp,alpha=ma)
    counts={i:int(((ml==i)&(ma>0)).sum()) for i in range(len(mp))}
    colors=[{'index':i,'hex':'#'+''.join(f'{v:02x}' for v in mp[i]),'pixels':counts[i],'rgb':mp[i].tolist()} for i in range(len(mp))]
    old_fp=palette_id(mp)
    (mwork/'palette.json').write_text(json.dumps({'width':w,'height':h,'fingerprint':old_fp,'colors':colors}),encoding='utf-8')
    run('vectorize.py','palette-merge',str(mwork),'--from','2','--into','1')
    data=np.load(mwork/'prepared.npz')
    assert (data['labels']==2).sum()==0 and data['labels'][20,20]==1
    expected=np.rint((mp[1].astype(float)*counts[1]+mp[2].astype(float)*counts[2])/(counts[1]+counts[2])).astype(np.uint8)
    assert np.array_equal(data['palette'][1],expected),'Merged color is not the pixel-weighted mean'
    assert np.array_equal(data['palette'][4],mp[4]) and len(data['palette'])==5,'Unrelated slots changed'
    entry={e['index']:e for e in json.loads((mwork/'palette.json').read_text(encoding='utf-8'))['colors']}
    assert entry[2]['pixels']==0 and entry[2]['merged_into']==1,'Source slot is not a tombstone'
    assert entry[1]['pixels']==counts[1]+counts[2] and entry[4]['pixels']==counts[4]
    merges=json.loads((mwork/'prepare-report.json').read_text(encoding='utf-8'))['merges']
    assert merges[0]['from']==2 and merges[0]['into']==1 and merges[0]['previous_fingerprint']==old_fp
    new_fp=palette_id(data['palette'])
    # Tombstone index stability: a plan above the merged slot (4 > 2) still traces.
    (mwork/'plan.json').write_text(json.dumps({'coordinate_size':[w,h],'palette_fingerprint':new_fp,'default':{'id':'paper','base':'#faf5eb','phase':'background'},'roles':{'ink':[3]},'regions':[{'id':'accent','base':'#fce196','polygon':[[20,20],[40,20],[40,50],[20,50]],'include_colors':[4]}]}),encoding='utf-8')
    run('vectorize.py','trace','--work',mwork,'--plan',mwork/'plan.json','--output',mwork/'illustration.svg')
    assert '#fce196' in (mwork/'illustration.svg').read_text(encoding='utf-8'),'Post-merge trace lost a slot above the tombstone'
    (mwork/'stale.json').write_text(json.dumps({'coordinate_size':[w,h],'palette_fingerprint':old_fp,'default':{'id':'paper','base':'#faf5eb'}}),encoding='utf-8')
    stale=run('vectorize.py','trace','--work',mwork,'--plan',mwork/'stale.json','--output',mwork/'stale.svg',expected=1)
    assert 'Palette changed' in stale.stderr,'Stale plan after merge was accepted'
    run('vectorize.py','palette-merge',str(mwork),'--from','2','--into','1',expected=1)
    run('vectorize.py','palette-merge',str(mwork),'--from','3','--into','3',expected=1)
    run('vectorize.py','palette-merge',str(mwork),'--from','9','--into','1',expected=1)
    passed+=['palette_merge_tombstone','merge_weighted_mean','merge_index_stability','merge_audit_trail','stale_plan_after_merge_rejected','merge_rejections']
    # Oversize limits warn and record but never alter or fail the geometry.
    run('vectorize.py','trace','--work',work,'--plan',work/'plan.json','--output',work/'limited.svg','--line-art',work/'limited-lines.svg','--max-paths','1','--max-bytes','10')
    trace_report=json.loads((work/'trace-report.json').read_text(encoding='utf-8'))
    assert trace_report['oversize']==[{'kind':'paths','value':trace_report['native_paths'],'limit':1},{'kind':'bytes','value':trace_report['svg_bytes'],'limit':10}] and trace_report['native_paths']>1
    assert (work/'limited.svg').exists() and (work/'limited.svg').stat().st_size>10
    run('vectorize.py','trace','--work',work,'--plan',work/'plan.json','--output',work/'limited2.svg','--line-art',work/'limited2-lines.svg')
    assert (work/'limited2.svg').read_bytes()==(work/'illustration.svg').read_bytes(),'Limits or report changes altered final geometry'
    passed+=['oversize_reported','limits_preserve_geometry']
    # Fidelity axis trades detail for size across stages.
    run('vectorize.py','trace','--work',work,'--plan',work/'plan.json','--output',work/'faith.svg','--fidelity','faithful')
    run('vectorize.py','trace','--work',work,'--plan',work/'plan.json','--output',work/'compact.svg','--fidelity','compact')
    assert (work/'compact.svg').stat().st_size<=(work/'faith.svg').stat().st_size,'Compact fidelity did not reduce size'
    passed.append('fidelity_axis')
    report={'passed':passed,'cleanup':reports,'synthetic_comparison':result['global'],'note':'Automated invariants; real-image visual inspection remains separate.'}
    (work/'quality-test-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if __name__=='__main__':main()
