"""Consolidated-mode regressions: consolidation, role preservation, island removal, guards."""
import argparse,json,subprocess,sys
from pathlib import Path
import numpy as np
import pymupdf
from PIL import Image
from vectorize import palette_id
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
    w,h=128,96
    palette=np.array([[250,245,235],[110,180,120],[50,50,50],[58,58,58],[127,191,137],[255,255,255]],np.uint8)
    labels=np.full((h,w),0,np.uint16);labels[48:,:]=1
    labels[50:56,15:35]=4
    for x0,y0 in ((60,55),(75,60),(40,70),(90,85)):labels[y0:y0+2,x0:x0+2]=4
    for i,x in enumerate(range(10,118,12)):labels[19:21,x:min(118,x+12)]=2 if i%2==0 else 3
    labels[69:72,14:17]=5
    alpha=np.full((h,w),255,np.uint8);fp=palette_id(palette)
    def scene(dst,alphas):
        np.savez_compressed(dst/'prepared.npz',labels=labels,palette=palette,alpha=alphas)
        (dst/'plan.json').write_text(json.dumps({'coordinate_size':[w,h],'palette_fingerprint':fp,'default':{'id':'scene','name':'Scene','base':'#faf5eb','phase':'background'},'roles':{'ink':[2,3],'color':[1],'highlight':[5]}}),encoding='utf-8')
    scene(work,alpha)
    run('consolidate_trace.py','--work',work,'--plan',work/'plan.json','--output',work/'consolidated.svg','--line-art',work/'lines.svg')
    svg=(work/'consolidated.svg').read_text(encoding='utf-8')
    report=json.loads((work/'consolidated.consolidate-report.json').read_text(encoding='utf-8'))
    assert report['mode']=='consolidated' and report['input_palette']==fp and report['toolkit_version']==VERSION
    region=report['regions'][0]
    assert region['pigments_before']==6 and region['pigments_after']==5,'Ink shades were not consolidated'
    assert region['merged_islands']==4 and region['reassigned_pixels']==16,'Antialias islands were not merged'
    assert 'drawing-paper' in svg and '#6eb478' in svg,'Global fill palette or opaque canvas lost'
    assert '#7fbf89' in svg,'Legitimate broad light paint was erased with the speckles'
    validate_ok=load_svg(work/'consolidated.svg')
    doc=pymupdf.open(work/'consolidated.svg');page=doc[0]
    pix=page.get_pixmap(matrix=pymupdf.Matrix(w/page.rect.width,h/page.rect.height),alpha=True)
    pix.save(work/'render.png');rgba=np.asarray(Image.open(work/'render.png').convert('RGBA'))
    assert rgba.shape==(h,w,4),'Rendered dimensions changed'
    def px(x,y):return rgba[y,x,:3].astype(int)
    for x in (16,40,64,88,112):assert px(x,20).max()<120,'Consolidated ink line broken or lightened at x=%d'%x
    for x0,y0 in ((60,55),(75,60),(40,70),(90,85)):assert np.linalg.norm(px(x0,y0)-[110,180,120])<45,'Island at %d,%d was not absorbed by local paint'%(x0,y0)
    assert np.linalg.norm(px(20,52)-[127,191,137])<45,'Broad light paint patch was not preserved'
    assert px(15,70).min()>200,'Protected highlight was destroyed'
    assert np.linalg.norm(px(64,10)-[250,245,235])<45,'Background base drifted'
    assert any(n.get('data-region')=='scene' for n in load_svg(work/'consolidated.svg').iter()),'Semantic region groups missing for replay'
    passed+=['ink_consolidation','island_removal','role_palette_preserved','protected_highlight','opaque_canvas','semantic_regions']
    # Partial alpha must be rejected, not silently flattened.
    w2=work/'alpha-case';w2.mkdir()
    alpha2=np.full((h,w),255,np.uint8);alpha2[5,5]=128
    scene(w2,alpha2)
    rejected=run('consolidate_trace.py','--work',w2,'--plan',w2/'plan.json','--output',w2/'consolidated.svg',expected=1)
    assert 'opaque' in rejected.stderr,'Partial-alpha source was not rejected with guidance'
    passed.append('partial_alpha_rejected')
    # Replay demo must accept consolidated output; faithful route must stay available on the same work.
    run('make_demo.py',work/'consolidated.svg','--output',work/'index.html')
    run('vectorize.py','trace','--work',work,'--plan',work/'plan.json','--output',work/'faithful.svg')
    faithful=(work/'faithful.svg').read_text(encoding='utf-8')
    assert '#7fbf89' in faithful,'Faithful trace no longer keeps the antialias tint'
    passed+=['demo_accepts_consolidated','faithful_route_unchanged']
    print(json.dumps({'passed':passed,'work':str(work)}))
if __name__=='__main__':main()
