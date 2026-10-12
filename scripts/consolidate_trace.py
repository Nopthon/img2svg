"""Appearance-aware consolidated vectors: merge pigment, cover seams.
Explicit opt-in alternative to pixel-fidelity tracing; geometry reuses the
faithful polyline contour engine, so magnified boundaries stay honest segments.
Inspect native SVG at 1x AND at high zoom before delivering.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import cv2
import numpy as np
from vectorize import load_prepared,role_for,node,color,save_json,TONES,palette_id,contours_to_path
from svg_compat import write_svg,validate
from version import VERSION

def consolidate(palette,counts,roles,distance,role_distances=None):
    role_distances=role_distances or {}
    groups=[{'members':[i],'rgb':palette[i].astype(float),'count':int(n),'role':roles[i]} for i,n in enumerate(counts) if n]
    while True:
        best=None
        for i,a in enumerate(groups):
            for j in range(i+1,len(groups)):
                b=groups[j]
                if a['role']!=b['role']:continue
                delta=float(np.linalg.norm(a['rgb']-b['rgb']))
                if delta<=role_distances.get(a['role'],distance) and (best is None or delta<best[0]):best=(delta,i,j)
        if best is None:break
        _,i,j=best;a,b=groups[i],groups[j];n=a['count']+b['count']
        groups[i]={'members':a['members']+b['members'],'rgb':(a['rgb']*a['count']+b['rgb']*b['count'])/n,'count':n,'role':a['role']};groups.pop(j)
    return groups

def merge_fragments(codes,owned,groups,area,protect_area,keep_long):
    seeds=np.zeros(owned.shape,bool);discard=np.zeros_like(seeds);removed=0
    for ci,g in enumerate(groups):
        m=np.uint8(owned&(codes==ci));n,cc,stats,_=cv2.connectedComponentsWithStats(m,8)
        threshold=protect_area if g['role'] in ('ink','detail','highlight') else area
        keep=np.zeros(n,bool)
        for k in range(1,n):
            _,_,w,h,size=stats[k];keep[k]=size>=threshold or max(w,h)>=keep_long
        if not keep[1:].any() and n>1:keep[1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]))]=True
        seeds|=keep[cc];bad=(cc>0)&~keep[cc];discard|=bad;removed+=int((~keep[1:]).sum())
    if discard.any() and seeds.any():
        _,nearest=cv2.distanceTransformWithLabels(np.uint8(~seeds),cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
        lookup=np.r_[0,codes[seeds]]
        result=codes.copy();result[discard]=lookup[nearest[discard]]
        # A thin line often contains many short differently colored pieces.
        # Recolor those pieces WITHIN the ink role, preserving the union ribbon.
        # Otherwise a component-area filter erases an apparently dotted line.
        for ci,g in enumerate(groups):
            if g['role'] not in ('ink','highlight'):continue
            target=discard&(codes==ci)
            if not target.any():continue
            allowed=[i for i,q in enumerate(groups) if q['role']==g['role'] and ('rgb' not in g or 'rgb' not in q or np.linalg.norm(g['rgb']-q['rgb'])<=50)]
            stable=seeds&np.isin(codes,allowed)
            if stable.any():
                distance,nearest=cv2.distanceTransformWithLabels(np.uint8(~stable),cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
                lookup=np.r_[0,codes[stable]];replacement=lookup[nearest[target]]
                # Search among compatible pigments, not merely the closest dark
                # core. Otherwise every antialias island survives needlessly.
                safe=distance[target]<=max(3,keep_long)
                result[target]=np.where(safe,replacement,codes[target])
            else:result[target]=codes[target]
    else:result=codes
    return result,{'merged_islands':removed,'reassigned_pixels':int(discard.sum())}

def close_small_holes(mask,area):
    n,cc,stats,_=cv2.connectedComponentsWithStats(np.uint8(~mask),8)
    take=np.zeros(n,bool)
    h,w=mask.shape
    for i in range(1,n):
        x,y,bw,bh,size=stats[i]
        # Thin negative-space slivers between adjacent shapes are real gaps.
        # Only compact enclosed pinholes are eligible for an explicit repair.
        compact=max(bw,bh)/max(1,min(bw,bh))<=1.8 and size/(bw*bh)>=.35
        if size<=area and compact and x>0 and y>0 and x+bw<w and y+bh<h:take[i]=True
    return mask|take[cc]

def component_backings(mask,local,palette,owned,base=None,small_area=64):
    """Use the actual local pigment under detached edge pieces, not a dark
    region-wide average. A pale highlight must not acquire the outline color.
    Broad base silhouettes can retain the explicitly authored base color.
    """
    n,cc,stats,_=cv2.connectedComponentsWithStats(np.uint8(mask),8)
    if n<=1:return
    weights=np.bincount(cc[mask&owned],minlength=n)
    rgb_sums=np.column_stack([np.bincount(cc[mask&owned],weights=palette[local[mask&owned],d],minlength=n) for d in range(3)])
    colors=[]
    for i in range(1,n):
        if base is not None and stats[i,cv2.CC_STAT_AREA]>=small_area:paint=base
        elif weights[i]:
            mean=rgb_sums[i]/weights[i]
            paint=color(palette[np.argmin(np.sum((palette.astype(float)-mean)**2,axis=1))])
        else:paint=base or '#808080'
        colors.append(paint)
    # Group components by paint without creating one SVG path per sample.
    unique=sorted(set(colors));lut=np.full(n,-1,np.int32)
    lookup={c:i for i,c in enumerate(unique)}
    for i,c in enumerate(colors,1):lut[i]=lookup[c]
    assigned=lut[cc]
    for i,c in enumerate(unique):yield c,assigned==i

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='img2svg '+VERSION)
    p.add_argument('--work',required=True);p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
    p.add_argument('--merge-distance',type=float,default=22);p.add_argument('--min-area',type=int,default=12)
    p.add_argument('--epsilon',type=float,default=.55);p.add_argument('--overlap',type=float,default=.4)
    p.add_argument('--report');a=p.parse_args()
    if not 0<=a.merge_distance<=50 or not 1<=a.min_area<=100 or not .05<=a.epsilon<=2 or not 0<=a.overlap<=2:p.error('Consolidation parameters outside supported bounds')
    plan=json.loads(Path(a.plan).read_text(encoding='utf-8-sig'))
    labels,palette,alpha,regions,mapping=load_prepared(a.work,plan);h,w=labels.shape
    if np.any((alpha!=0)&(alpha!=255)):raise ValueError('Consolidated mode currently requires opaque/binary-alpha input; use faithful mode for partial transparency')
    root=node('svg',{'id':'illustration','version':'1.1','width':w,'height':h,'viewBox':f'0 0 {w} {h}','preserveAspectRatio':'xMidYMid meet'})
    title=node('title');title.text=plan.get('title','Consolidated vector reconstruction');root.append(title)
    desc=node('desc');desc.text='Native reconstruction with consolidated pigment regions. No embedded image.';root.append(desc)
    # An opaque source needs an opaque canvas beneath local fitted silhouettes.
    # This is native geometry, not a raster hidden behind the trace.
    if np.all(alpha==255):
        root.append(node('rect',{'id':'drawing-paper','x':0,'y':0,'width':w,'height':h,'fill':regions[0]['base'],'stroke':'none'}))
    art=node('g',{'id':'artwork'});root.append(art);report=[];paths=0;vertices=0;contours=0
    for ri,r in enumerate(regions):
        ys,xs=np.where((mapping==ri)&(alpha>0))
        if not len(xs):continue
        x,y=int(xs.min()),int(ys.min());bw,bh=int(xs.max()-x+1),int(ys.max()-y+1)
        owned=(mapping[y:y+bh,x:x+bw]==ri)&(alpha[y:y+bh,x:x+bw]>0);local=labels[y:y+bh,x:x+bw]
        settings=r.get('consolidate',{});merge=float(settings.get('merge_distance',a.merge_distance));area=int(settings.get('min_area',a.min_area));epsilon=float(settings.get('epsilon',a.epsilon));overlap=float(settings.get('overlap',a.overlap))
        protected=int(settings.get('protected_area',4));long=float(settings.get('keep_long',10))
        overrides=settings.get('role_merge_distances',{})
        if not isinstance(overrides,dict) or any(role not in TONES or not 0<=float(v)<=50 for role,v in overrides.items()):raise ValueError('Invalid role_merge_distances in '+r['id'])
        # A shared fill pigment must not become white or a different hue
        # just because another semantic crop contains more background.
        # Preserve global fill swatches by default; consolidate ink locally.
        # Explicit role overrides permit deliberate local fill simplification.
        role_distances={role:0. for role in TONES if role!='ink'}
        role_distances.update({role:float(v) for role,v in overrides.items()})
        if not 0<=merge<=50 or not 1<=area<=100 or not 1<=protected<=100 or not .05<=epsilon<=2 or not 0<=overlap<=2 or long<1:raise ValueError('Invalid consolidate settings in '+r['id'])
        if any(not 0<=int(settings.get(key,0))<=100 for key in ('base_hole_area','ink_hole_area')):raise ValueError('Hole repair area must be 0..100')
        if np.any(alpha!=255) and any(settings.get(key,0) for key in ('base_hole_area','ink_hole_area')):raise ValueError('Hole repair needs an opaque source; preserve transparent negative space')
        counts=np.bincount(local[owned],minlength=len(palette));roles=[role_for(r,i,plan.get('roles',{})) for i in range(len(palette))]
        groups=consolidate(palette,counts,roles,merge,role_distances);lookup=np.zeros(len(palette),np.int16)
        for i,g in enumerate(groups):
            for ci in g['members']:lookup[ci]=i
        codes=lookup[local];codes,removed=merge_fragments(codes,owned,groups,area,protected,long)
        group=node('g',{'id':r['id'],'data-region':r['id'],'data-base':r['base'],'transform':f'translate({x} {y})'});art.append(group)
        layers={}
        def layer(tone):
            if tone not in layers:layers[tone]=node('g',{'id':r['id']+'-'+tone,'data-tone':tone})
            return layers[tone]
        def paint(mask,paint_hex,tone,identity,stroke=overlap):
            nonlocal paths,vertices,contours
            d,n,c=contours_to_path(np.uint8(mask)*255,epsilon)
            if not d:return
            layer(tone).append(node('path',{'id':r['id']+'-'+identity,'d':d,'fill':paint_hex,'stroke':paint_hex if stroke else 'none','stroke-width':stroke,'stroke-linejoin':'round','stroke-linecap':'round','fill-rule':'evenodd'}))
            paths+=1;vertices+=n;contours+=c
        # A real local base silhouette covers gaps between fitted color islands.
        base_tone='background' if r.get('phase')=='background' else 'color'
        base_mask=close_small_holes(owned,int(settings.get('base_hole_area',0)))
        for bi,(bc,bm) in enumerate(component_backings(base_mask,local,palette,owned,r['base'])):
            paint(bm,bc,base_tone,f'base-silhouette-{bi}',stroke=min(.15,overlap) if bc!=r['base'] else overlap)
        ink_groups=[i for i,g in enumerate(groups) if g['role']=='ink']
        if ink_groups:
            ink=owned&np.isin(codes,ink_groups)
            # Opaque backing repairs only tiny enclosed holes in an ink ribbon.
            ink=close_small_holes(ink,int(settings.get('ink_hole_area',0)))
            for bi,(bc,bm) in enumerate(component_backings(ink,local,palette,owned)):
                paint(bm,bc,'ink',f'continuous-ink-backing-{bi}',stroke=min(.3,overlap))
        for ci,g in sorted(enumerate(groups),key=lambda z:-float(z[1]['rgb'].mean())):
            m=owned&(codes==ci)
            if not m.any():continue
            paint(m,color(np.round(g['rgb'])),g['role'],f'paint-{ci}',stroke=min(.20,overlap) if g['role']=='ink' else overlap)
        for tone in TONES:
            if tone in layers:group.append(layers[tone])
        report.append(dict(region=r['id'],pigments_before=int(np.count_nonzero(counts)),pigments_after=len(groups),settings={'merge_distance':merge,'role_merge_distances':role_distances,'min_area':area,'epsilon':epsilon,'overlap':overlap,'protected_area':protected,'keep_long':long,'base_hole_area':int(settings.get('base_hole_area',0)),'ink_hole_area':int(settings.get('ink_hole_area',0))},**removed))
    validate(root);write_svg(root,a.output)
    data={'mode':'consolidated','toolkit_version':VERSION,'input_palette':palette_id(palette),'plan_sha256':hashlib.sha256(Path(a.plan).read_bytes()).hexdigest(),'svg_bytes':Path(a.output).stat().st_size,'paths':paths,'closed_contours':contours,'vertices':vertices,'regions':report,'parameters':{'merge_distance':a.merge_distance,'min_area':a.min_area,'epsilon':a.epsilon,'overlap':a.overlap},'note':'Deliberately consolidates texture for a cleaner enlarged look; compare whole image and zoom crops before accepting.'}
    target=a.report or str(Path(a.output).with_suffix('.consolidate-report.json'));save_json(target,data)
    print(json.dumps({k:v for k,v in data.items() if k!='regions'}))
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
