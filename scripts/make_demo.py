"""Wrap a portable, semantic SVG in an offline, dependency-free drawing demo."""
import argparse,copy,html,json
from pathlib import Path
import xml.etree.ElementTree as ET
from svg_compat import NS,load_svg,normalize,validate,tag
from version import VERSION

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='img2svg '+VERSION)
    p.add_argument('svg');p.add_argument('--output',required=True);p.add_argument('--line-art');p.add_argument('--plan');p.add_argument('--title',default='Drawing replay');p.add_argument('--duration',type=float,default=48)
    a=p.parse_args()
    if a.duration<5:p.error('duration must be >= 5 seconds')
    root=load_svg(a.svg);validate(root);root.set('id','illustration')
    vb=[float(n) for n in root.get('viewBox').replace(',',' ').split()];w,h=vb[2:]
    artwork=next((n for n in root.iter() if n.get('id')=='artwork'),None)
    if artwork is None:raise ValueError('Expected g id="artwork" with semantic data-region / data-tone groups')
    parts=[n for n in artwork if n.get('data-region')]
    if not parts:raise ValueError('No semantic data-region groups; make a painting plan first')
    plan=json.loads(Path(a.plan).read_text(encoding='utf-8-sig')) if a.plan else {}
    guides=ET.SubElement(root,'{'+NS+'}g',{'id':'demo-guides','opacity':'0','fill':'none','stroke':'#8c9690','stroke-width':'1.4','stroke-linecap':'round'})
    cw,ch=plan.get('coordinate_size',[w,h]);guides.set('transform',f'scale({w/cw:g} {h/ch:g})')
    for i,g in enumerate(plan.get('construction',[])):
        attrs={'id':f'guide-{i}','d':g['d'],'fill':'none','stroke':g.get('stroke','#8c9690'),'stroke-width':str(g.get('width',1.4))}
        ET.SubElement(guides,'{'+NS+'}path',attrs)
    pencil=ET.SubElement(root,'{'+NS+'}g',{'id':'demo-pencil','opacity':'0'})
    if a.line_art:
        drawing=normalize(load_svg(a.line_art))
        if [float(v) for v in drawing.get('viewBox').split()]!=vb:raise ValueError('Line art viewBox differs from artwork')
        for child in drawing:
            if tag(child) not in ('title','desc','metadata'):pencil.append(copy.deepcopy(child))
    validate(root)
    tones={n.get('data-tone') for n in artwork.iter() if n.get('data-tone')}
    candidates=[('Sketch',0,.08,bool(len(guides))),
                ('Line art',.08,.34,'ink' in tones or bool(len(pencil))),
                ('Base color',.34,.62,bool(tones & {'color','shadow','highlight','background'})),
                ('Shadow',.62,.80,'shadow' in tones),
                ('Highlight',.80,.92,'highlight' in tones),
                ('Finish',.92,1,True)]
    active=[(name,start,end) for name,start,end,enabled in candidates if enabled]
    weight=sum(end-start for _,start,end in active);cursor=0;phases=[]
    for name,start,end in active:
        finish=cursor+(end-start)/weight
        phases.append({'name':name,'start':cursor,'end':finish,'from':start,'to':end});cursor=finish
    phases[-1]['end']=1
    buttons=''.join(f'<button class="step" data-seek="{phase["end"]:.10f}"><span>{i:02d}</span>{phase["name"]}</button>' for i,phase in enumerate(phases,1))
    template=(Path(__file__).resolve().parents[1]/'assets/demo.html').read_text(encoding='utf-8')
    svg=ET.tostring(root,encoding='unicode')
    data=template.replace('@@ARTWORK@@',svg).replace('@@TITLE@@',html.escape(a.title)).replace('@@RATIO@@',f'{w/h:.10f}').replace('@@DURATION@@',str(round(a.duration*1000))).replace('@@STEPS@@',buttons).replace('@@PHASES@@',json.dumps(phases,ensure_ascii=True))
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(data,encoding='utf-8')
    print(json.dumps({'html':str(out),'bytes':out.stat().st_size,'regions':len(parts),'duration_seconds':a.duration,'stages':[n['name'] for n in phases],'toolkit_version':VERSION,'external_dependencies':0}))
if __name__=='__main__':main()
