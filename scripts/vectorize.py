"""Two-pass raster-reference to semantic native SVG. See references/plan-schema.md."""
import argparse, io, json, math, re, hashlib, sys
from pathlib import Path
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from PIL import Image, ImageOps, ImageCms
from svg_compat import NS, validate, write_svg
from version import VERSION

ET.register_namespace('',NS)
TONES=('background','color','shadow','highlight','detail','ink')
def node(name,attrs=None):return ET.Element('{'+NS+'}'+name,{k:str(v) for k,v in (attrs or {}).items()})
def save_json(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def color(c):return '#'+''.join(f'{int(v):02x}' for v in c)
def palette_id(palette):return hashlib.sha256(np.asarray(palette,dtype=np.uint8).tobytes()).hexdigest()
def image_rgba(path):
    im=ImageOps.exif_transpose(Image.open(path))
    profile=im.info.get('icc_profile');rgba=im.convert('RGBA')
    if profile:
        rgb=ImageCms.profileToProfile(im.convert('RGB'),ImageCms.ImageCmsProfile(io.BytesIO(profile)),ImageCms.createProfile('sRGB'),outputMode='RGB')
        rgba=rgb.convert('RGBA');rgba.putalpha(im.convert('RGBA').getchannel('A'))
    return np.asarray(rgba)

def prepare(a):
    work=Path(a.work);work.mkdir(parents=True,exist_ok=True)
    rgba=image_rgba(a.input);rgb=rgba[:,:,:3];alpha=rgba[:,:,3];h,w=alpha.shape
    visible=alpha>0
    if not visible.any():raise ValueError('Reference is fully transparent')
    smooth=cv2.bilateralFilter(rgb,5,a.denoise,3) if a.denoise else rgb
    lab=cv2.cvtColor(smooth,cv2.COLOR_RGB2LAB)
    step=a.sample_step or max(1,int(math.sqrt(h*w/320000)))
    sample=lab[::step,::step][visible[::step,::step]].astype(np.float32)
    if not len(sample):sample=lab[visible].astype(np.float32)
    for focus in a.focus:
        x,y,fw,fh=[int(v) for v in focus.split(',')]
        if min(x,y)<0 or min(fw,fh)<=0 or x+fw>w or y+fh>h:raise ValueError('Focus box is outside reference')
        crop=lab[y:y+fh,x:x+fw][visible[y:y+fh,x:x+fw]][::max(1,step)]
        sample=np.concatenate([sample,crop.astype(np.float32)])
    k=min(a.colors,len(np.unique(sample,axis=0)))
    cv2.setRNGSeed(a.seed)
    _,_,centres=cv2.kmeans(sample,k,None,(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,80,.05),3,cv2.KMEANS_PP_CENTERS)
    labels=np.zeros((h,w),np.uint16)
    rows=max(1,int(64_000_000/(w*k*3*4)))
    for start in range(0,h,rows):
        delta=lab[start:start+rows].astype(np.float32)[...,None,:]-centres
        labels[start:start+rows]=np.argmin(np.sum(delta*delta,axis=-1),axis=-1)
    palette=[];entries=[]
    for i in range(k):
        m=(labels==i)&visible
        c=np.round(rgb[m].mean(axis=0)).astype(np.uint8) if m.any() else np.array([0,0,0],np.uint8)
        palette.append(c);entries.append({'index':i,'hex':color(c),'pixels':int(m.sum()),'rgb':c.tolist()})
    palette=np.array(palette)
    reconstructed=np.dstack([palette[labels],alpha])
    Image.fromarray(reconstructed).save(work/'quantized-preview.png')
    np.savez_compressed(work/'prepared.npz',labels=labels,palette=palette,alpha=alpha)
    save_json(work/'palette.json',{'width':w,'height':h,'fingerprint':palette_id(palette),'colors':entries})
    report={'source':str(Path(a.input).resolve()),'source_sha256':hashlib.sha256(Path(a.input).read_bytes()).hexdigest(),'width':w,'height':h,'palette_size':k,'seed':a.seed,'denoise':a.denoise,'sample_step':step,'focus':a.focus,'palette_fingerprint':palette_id(palette),'toolkit_version':VERSION,'opencv':cv2.__version__,'numpy':np.__version__,'has_transparency':bool((alpha<255).any()),'quantization_rgb_mae':float(np.abs(rgb.astype(float)-palette[labels].astype(float))[visible].mean())}
    save_json(work/'prepare-report.json',report);print(json.dumps(report,ensure_ascii=False))

def remap_plan_indices(plan,source,target):
    """Rewrite every palette index reference so `source` becomes `target`, keeping
    list order, de-duplicating, and never leaving one index in two roles of a map."""
    def fix(obj):
        for key in ('include_colors','exclude_colors'):
            if key in obj:
                seen=[];out=[]
                for i in obj[key]:
                    j=target if i==source else i
                    if j not in seen:seen.append(j);out.append(j)
                obj[key]=out
        if 'roles' in obj:
            used=set();roles={}
            for role,ids in obj['roles'].items():
                keep=[]
                for i in ids:
                    j=target if i==source else i
                    if j not in used:used.add(j);keep.append(j)
                if keep:roles[role]=keep
            obj['roles']=roles
    fix(plan)
    for r in plan.get('regions',[]):fix(r)
    for r in plan.get('assignments',[]):fix(r)
    return plan

def palette_merge(a):
    work=Path(a.work)
    data=np.load(work/'prepared.npz',allow_pickle=False)
    labels,palette,alpha=data['labels'],data['palette'],data['alpha']
    k=len(palette)
    if not 0<=a.source<k or not 0<=a.target<k:raise ValueError(f'Palette index out of range 0..{k-1}')
    if a.source==a.target:raise ValueError('--from and --into must differ')
    info=json.loads((work/'palette.json').read_text(encoding='utf-8'))
    entries={e['index']:e for e in info['colors']}
    source=entries.get(a.source)
    if source is None or source.get('merged_into') is not None or int(source.get('pixels',0))==0:
        raise ValueError(f'Palette slot {a.source} is a tombstone or missing; merge live colors only')
    counts={e['index']:int(e.get('pixels',0)) for e in info['colors']}
    total=counts[a.target]+counts[a.source]
    if total==0:raise ValueError('Both palette slots are empty')
    old_fingerprint=info['fingerprint']
    # Mean over the union mask equals the pixel-count-weighted mean of the two entries,
    # so no source-image re-read is needed and the result matches prepare's rounding.
    merged=np.rint((palette[a.target].astype(float)*counts[a.target]+palette[a.source].astype(float)*counts[a.source])/total).astype(np.uint8)
    labels=labels.copy();labels[labels==a.source]=a.target
    palette=palette.copy();palette[a.target]=merged
    np.savez_compressed(work/'prepared.npz',labels=labels,palette=palette,alpha=alpha)
    Image.fromarray(np.dstack([palette[labels],alpha])).save(work/'quantized-preview.png')
    new_fingerprint=palette_id(palette)
    info['fingerprint']=new_fingerprint
    for e in info['colors']:
        if e['index']==a.target:
            e['hex']=color(merged);e['rgb']=merged.tolist();e['pixels']=total
        elif e['index']==a.source:
            # Tombstone keeps the slot so indices above it never shift.
            e['pixels']=0;e['merged_into']=a.target
    save_json(work/'palette.json',info)
    report_path=work/'prepare-report.json'
    report=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    report.setdefault('merges',[]).append({'from':a.source,'into':a.target,'merged_hex':color(merged),'previous_fingerprint':old_fingerprint,'toolkit_version':VERSION})
    report['palette_fingerprint']=new_fingerprint
    if 'quantization_rgb_mae' in report:report['quantization_rgb_mae']=None
    save_json(report_path,report)
    plan_remapped=None
    if a.plan:
        plan_path=Path(a.plan)
        plan=json.loads(plan_path.read_text(encoding='utf-8-sig'))
        if plan.get('palette_fingerprint') and plan['palette_fingerprint']!=old_fingerprint:
            print('warning: plan palette_fingerprint does not match the pre-merge palette; remapping anyway',file=sys.stderr)
        remap_plan_indices(plan,a.source,a.target)
        plan['palette_fingerprint']=new_fingerprint
        out_path=Path(a.plan_out) if a.plan_out else plan_path
        out_path.parent.mkdir(parents=True,exist_ok=True)
        out_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        plan_remapped=str(out_path.resolve())
        report.setdefault('merges',[])[-1]['plan_remapped']=plan_remapped
        save_json(report_path,report)
    print(json.dumps({'work':str(work.resolve()),'from':a.source,'into':a.target,'hex':color(merged),'pixels':total,'fingerprint':new_fingerprint,'plan_remapped':plan_remapped},ensure_ascii=False))

def draft_plan(a):
    """Propose a plan skeleton: one region per live palette color, with simplified
    outer polygons from its connected components. Rename regions and set roles."""
    work=Path(a.work)
    data=np.load(work/'prepared.npz',allow_pickle=False)
    labels,palette,alpha=data['labels'],data['palette'],data['alpha']
    h,w=labels.shape;visible=alpha>0
    fingerprint=palette_id(palette)
    info_path=work/'palette.json'
    if info_path.exists():
        info=json.loads(info_path.read_text(encoding='utf-8'))
        fingerprint=info.get('fingerprint',fingerprint)
        dead={e['index'] for e in info.get('colors',[]) if int(e.get('pixels',0))==0}
    else:dead=set()
    regions=[];skipped=0
    for ci in range(len(palette)):
        if ci in dead:continue
        m=np.uint8((labels==ci)&visible)
        if not m.any():continue
        count,cc,stats,_=cv2.connectedComponentsWithStats(m,8)
        polys=[]
        for k in range(1,count):
            if stats[k,cv2.CC_STAT_AREA]<a.min_area:continue
            cs,_=cv2.findContours(np.uint8(cc==k),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for c in cs:
                if len(c)<3:continue
                p=cv2.approxPolyDP(c,a.epsilon,True).reshape(-1,2)
                if len(p)>=3:polys.append([[int(x),int(y)] for x,y in p])
        if not polys:skipped+=1;continue
        hexc=color(palette[ci])
        phase='ink' if a.ink_threshold>0 and int(max(palette[ci]))<a.ink_threshold else 'color'
        regions.append({'id':f'palette-{ci}','name':f'Palette {ci} {hexc}','include_colors':[ci],'base':hexc,'phase':phase,'polygons':polys,'draft':{'pixels':int(m.sum()),'components':count-1,'polygons':len(polys)}})
    regions.sort(key=lambda r:-r['draft']['pixels'])
    if a.max_regions>0:regions=regions[:a.max_regions]
    dominant=color(palette[int(np.bincount(labels[visible],minlength=len(palette)).argmax())])
    plan={'title':'Auto draft plan','coordinate_size':[w,h],'palette_fingerprint':fingerprint,'default':{'id':'unassigned','name':'Unassigned','base':dominant,'phase':'background'},'roles':{},'regions':regions,'draft_meta':{'generated_by':'img2svg draft-plan','toolkit_version':VERSION,'min_area':a.min_area,'epsilon':a.epsilon,'regions':len(regions),'skipped_colors':skipped,'note':'Auto-proposed polygons from connected components. Rename regions, assign roles/ink, and split or merge as needed before tracing.'}}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'draft_plan':str(out.resolve()),'regions':len(regions),'polygons':sum(len(r['polygons']) for r in regions),'skipped_colors':skipped,'width':w,'height':h},ensure_ascii=False))

def plan_regions(plan,labels):
    h,w=labels.shape;cw,ch=plan.get('coordinate_size',[w,h])
    if cw<=0 or ch<=0:raise ValueError('coordinate_size must be positive')
    if abs(cw/ch-w/h)>0.003*(w/h):raise ValueError('Plan coordinate aspect ratio differs from source; do not distort the reference')
    regions=[plan.get('default',{'id':'unassigned','name':'Unassigned visible pigment','base':'#ffffff'})]+plan.get('regions',[])
    seen=set();mapping=np.zeros((h,w),np.uint16)
    for i,r in enumerate(regions):
        rid=r.get('id','')
        if not re.fullmatch(r'[a-z][a-z0-9-]*',rid) or rid in seen:raise ValueError('Unique semantic lowercase region ID required: '+rid)
        seen.add(rid)
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',r.get('base','')):raise ValueError(rid+' requires literal base #RRGGBB')
        if r.get('phase','color') not in TONES:raise ValueError('Unknown phase')
        for role,ids in r.get('roles',{}).items():
            if role not in TONES:raise ValueError('Unknown pigment role '+role)
        assigned=[ci for values in r.get('roles',{}).values() for ci in values]
        if len(assigned)!=len(set(assigned)):raise ValueError('Duplicate color roles in '+rid)
    def apply_region(i,r):
        rid=regions[i]['id']
        polys=r.get('polygons',[r.get('polygon',[])])
        mask=np.zeros((h,w),np.uint8)
        for poly in polys:
            pts=np.asarray(poly,float)
            if pts.ndim!=2 or pts.shape[0]<3 or pts.shape[1]!=2 or not np.isfinite(pts).all():raise ValueError('Polygon needs at least 3 finite x,y pairs: '+rid)
            cv2.fillPoly(mask,[np.rint(pts*np.array([w/cw,h/ch])).astype(np.int32)],1)
        take=mask.astype(bool)
        if 'include_colors' in r:take&=np.isin(labels,r['include_colors'])
        if 'exclude_colors' in r:take&=~np.isin(labels,r['exclude_colors'])
        if 'only_from' in r:
            lookup={v['id']:j for j,v in enumerate(regions)}
            if any(v not in lookup for v in r['only_from']):raise ValueError('Unknown only_from region')
            take&=np.isin(mapping,[lookup[v] for v in r['only_from']])
        mapping[take]=i
    for i,r in enumerate(regions[1:],1):
        if 'polygon' in r or 'polygons' in r:apply_region(i,r)
    lookup={r['id']:i for i,r in enumerate(regions)}
    for assignment in plan.get('assignments',[]):
        if assignment.get('region') not in lookup:raise ValueError('Unknown assignment region')
        apply_region(lookup[assignment['region']],assignment)
    return regions,mapping

def load_prepared(work,plan):
    data=np.load(Path(work)/'prepared.npz',allow_pickle=False)
    labels,palette,alpha=data['labels'],data['palette'],data['alpha']
    prepared_report=Path(work)/'prepare-report.json'
    if plan.get('source_sha256'):
        report=json.loads(prepared_report.read_text(encoding='utf-8')) if prepared_report.exists() else {}
        if report.get('source_sha256')!=plan['source_sha256']:raise ValueError('Plan source_sha256 belongs to a different source image')
    if plan.get('palette_fingerprint') and plan['palette_fingerprint']!=palette_id(palette):
        raise ValueError('Palette changed: inspect new palette and rebuild role/filter indices')
    regions,mapping=plan_regions(plan,labels)
    for r in [plan]+regions+plan.get('assignments',[]):
        assigned=[ci for values in r.get('roles',{}).values() for ci in values]
        if len(assigned)!=len(set(assigned)):raise ValueError('Duplicate color roles in '+r.get('id','global plan'))
        for role,ids in r.get('roles',{}).items():
            if role not in TONES or any(type(v)!=int or not 0<=v<len(palette) for v in ids):raise ValueError('Invalid role or palette index')
        for key in ['include_colors','exclude_colors']:
            if any(type(v)!=int or not 0<=v<len(palette) for v in r.get(key,[])):raise ValueError('Invalid palette filter')
    return labels,palette,alpha,regions,mapping

def role_for(region,ci,global_roles):
    for role,ids in region.get('roles',{}).items():
        if ci in ids:return role
    for role,ids in global_roles.items():
        if ci in ids:return role
    return region.get('phase','color')

def merge_role_colors(palette,items,distance):
    """Union near-identical palette colors within one role and map each to the
    pixel-count-weighted mean, so pale near-duplicate pigments paint as one color."""
    parent=list(range(len(items)))
    def find(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    for i in range(len(items)):
        for j in range(i+1,len(items)):
            a,b=items[i][0],items[j][0]
            if float(np.linalg.norm(palette[a].astype(float)-palette[b].astype(float)))<=distance:
                ra,rb=find(i),find(j)
                if ra!=rb:parent[rb]=ra
    groups={}
    for i,(ci,cnt) in enumerate(items):groups.setdefault(find(i),[]).append((ci,cnt))
    result={}
    for members in groups.values():
        total=sum(c for _,c in members) or 1
        mean=np.rint(sum(palette[ci].astype(float)*c for ci,c in members)/total).astype(np.uint8)
        hexc=color(mean)
        for ci,_ in members:result[ci]=hexc
    return result

def path_data(points):
    p=np.asarray(points).reshape(-1,2).astype(float)/2+.25
    n=lambda v:format(v,'g')
    text=[f'M{n(p[0,0])} {n(p[0,1])}'];prev=p[0]
    for v in p[1:]:
        dx,dy=v-prev
        if dx==0:s='v'+n(dy)
        elif dy==0:s='h'+n(dx)
        else:
            absolute='L'+n(v[0])+' '+n(v[1]);relative='l'+n(dx)+' '+n(dy)
            s=relative if len(relative)<len(absolute) else absolute
        text.append(s);prev=v
    return ''.join(text)+'Z'

def contours_to_path(mask,epsilon):
    x,y,w,h=cv2.boundingRect(cv2.findNonZero(mask))
    up=cv2.resize(mask[y:y+h,x:x+w],(w*2,h*2),interpolation=cv2.INTER_NEAREST)
    cs,tree=cv2.findContours(up,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE,offset=(x*2,y*2))
    if tree is None:return '',0,0
    tree=tree[0];pieces=[];vertices=0;count=0
    def poly(c):
        ep=min(2*epsilon,max(.18,.23*math.sqrt(cv2.contourArea(c))))
        p=cv2.approxPolyDP(c,ep,True)
        return cv2.approxPolyDP(c,.30,True) if len(p)<3 else p
    for j,c in enumerate(cs):
        if tree[j][3]!=-1:continue
        p=poly(c)
        if len(p)<3:continue
        d=path_data(p);vertices+=len(p);count+=1
        child=tree[j][2]
        while child!=-1:
            p=poly(cs[child])
            if len(p)>2:d+=path_data(p);vertices+=len(p)
            child=tree[child][0]
        pieces.append((cv2.contourArea(c),d))
    pieces.sort(reverse=True)
    return ' '.join(d for _,d in pieces),vertices,count

def skeletonize(binary):
    a=np.pad(binary.astype(np.uint8),1)
    for _ in range(100):
        changed=0
        for phase in (0,1):
            p=a[1:-1,1:-1]
            n=[a[:-2,1:-1],a[:-2,2:],a[1:-1,2:],a[2:,2:],a[2:,1:-1],a[2:,:-2],a[1:-1,:-2],a[:-2,:-2]]
            total=sum(n);trans=sum((n[i]==0)&(n[(i+1)%8]==1) for i in range(8))
            common=(p==1)&(total>=2)&(total<=6)&(trans==1)
            drop=common&(n[0]*n[2]*n[4]==0)&(n[2]*n[4]*n[6]==0) if phase==0 else common&(n[0]*n[2]*n[6]==0)&(n[0]*n[4]*n[6]==0)
            changed+=int(drop.sum());p[drop]=0
        if not changed:break
    return a[1:-1,1:-1]

def line_art(mask,mapping,regions,w,h,path):
    distance=cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,3)
    sk=skeletonize(mask);sk[distance>4]=0
    nodes={int(y)*w+int(x) for y,x in np.argwhere(sk)}
    neighbors={p:[p+dy*w+dx for dy,dx in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)] if 0<=p%w+dx<w and p+dy*w+dx in nodes] for p in nodes}
    visited=set();lines=[]
    for start in sorted(nodes,key=lambda p:(len(neighbors[p])==2,p)):
        for nxt in neighbors[start]:
            edge=tuple(sorted((start,nxt)))
            if edge in visited:continue
            seq=[start];prev=start;cur=nxt;visited.add(edge)
            while True:
                seq.append(cur)
                options=[v for v in neighbors[cur] if v!=prev and tuple(sorted((cur,v))) not in visited]
                if len(neighbors[cur])!=2 or not options:break
                v=options[0];visited.add(tuple(sorted((cur,v))));prev,cur=cur,v
            if len(seq)<4:continue
            xy=np.array([[p%w+.5,p//w+.5] for p in seq],np.float32)
            length=float(np.linalg.norm(np.diff(xy,axis=0),axis=1).sum())
            if length<4:continue
            p=cv2.approxPolyDP(xy,.45,False).reshape(-1,2)
            owner=int(mapping[seq[len(seq)//2]//w,seq[len(seq)//2]%w])
            d='M'+' '.join(f'{v:g}' for v in p[0])+'L'+' '.join(f'{v:g}' for v in p[1:].ravel())
            width=np.clip(np.median([distance[p//w,p%w] for p in seq])*1.8,.8,3.2)
            lines.append((regions[owner].get('ink_order',owner),int(xy[:,1].min()),d,length,width))
    lines.sort(key=lambda v:(v[0],v[1]));total=sum(v[3] for v in lines) or 1;offset=0
    root=node('svg',{'viewBox':f'0 0 {w} {h}','width':w,'height':h,'version':'1.1'})
    for i,(_,__,d,length,width) in enumerate(lines):
        root.append(node('path',{'id':f'pencil-{i}','d':d,'fill':'none','stroke':'#71666a','stroke-width':f'{width:.2f}','stroke-linecap':'round','stroke-linejoin':'round','data-start':f'{offset/total:.6f}','data-span':f'{length/total:.6f}'}));offset+=length
    write_svg(root,path);return len(lines)

def trace(a):
    plan=json.loads(Path(a.plan).read_text(encoding='utf-8-sig'))
    labels,palette,alpha,regions,mapping=load_prepared(a.work,plan);h,w=labels.shape
    from region_cleanup import clean_regions
    labels,cleanup=clean_regions(labels,palette,alpha,mapping,regions,plan.get('roles',{}))
    root=node('svg',{'id':'illustration','version':'1.1','width':w,'height':h,'viewBox':f'0 0 {w} {h}','preserveAspectRatio':'xMidYMid meet'})
    title=node('title');title.text=plan.get('title','Reference reconstruction');root.append(title)
    artwork=node('g',{'id':'artwork'});root.append(artwork)
    vertex_count=contour_count=path_count=0;ink_mask=np.zeros((h,w),bool);coverage=[];merged_colors=set()
    packed=labels.astype(np.uint32)*256+alpha.astype(np.uint32)
    for ri,r in enumerate(regions):
        group=node('g',{'id':r['id'],'data-region':r['id'],'data-name':r.get('name',r['id']),'data-base':r['base'],'data-order':ri/max(1,len(regions)-1)})
        covered=(mapping==ri)&(alpha>0);coverage.append({'id':r['id'],'pixels':int(covered.sum())})
        if not covered.any():continue
        rep={}
        if a.merge_colors>0:
            vals,counts=np.unique(packed[covered],return_counts=True);by_role={}
            for code,cnt in zip(vals.tolist(),counts.tolist()):
                ci=code//256;role=role_for(r,ci,plan.get('roles',{}))
                role_counts=by_role.setdefault(role,{});role_counts[ci]=role_counts.get(ci,0)+int(cnt)
            for items in by_role.values():
                for ci,hexc in merge_role_colors(palette,list(items.items()),a.merge_colors).items():
                    rep[ci]=hexc
                    if hexc!=color(palette[ci]):merged_colors.add(ci)
        pigment={tone:[] for tone in TONES}
        for code in np.unique(packed[covered]):
            ci=int(code)//256;opacity=int(code)%256
            role=role_for(r,ci,plan.get('roles',{}));m=(mapping==ri)&(packed==code)
            if role=='ink':ink_mask|=m
            settings=r.get('trace',{});epsilon=settings.get('epsilon',a.epsilon)
            if 'dark_epsilon' in settings and max(palette[ci])<settings.get('dark_threshold',176):epsilon=settings['dark_epsilon']
            overlap=settings.get('overlap',a.overlap)
            if not 0<=epsilon<=2 or not 0<=overlap<=3:raise ValueError('Invalid regional trace settings')
            d,vertices,contours=contours_to_path(np.uint8(m)*255,min(epsilon,.2) if opacity<255 else epsilon)
            if not d:continue
            width=.55 if role=='ink' or opacity<255 else overlap
            paint=rep.get(ci,color(palette[ci]))
            attrs={'id':f'{r["id"]}-{role}-c{ci}-a{opacity}','fill':paint,'stroke':paint,'stroke-width':f'{width:g}','stroke-linejoin':'round','stroke-linecap':'round','fill-rule':'evenodd','d':d}
            if opacity<255:attrs['opacity']=f'{opacity/255:.6f}'
            pigment[role].append((float(palette[ci].mean()),node('path',attrs)))
            vertex_count+=vertices;contour_count+=contours;path_count+=1
        for tone in TONES:
            if not pigment[tone]:continue
            layer=node('g',{'id':f'{r["id"]}-{tone}','data-tone':tone,'data-order':ri/max(1,len(regions)-1)})
            for _,paint in sorted(pigment[tone],key=lambda v:-v[0]):layer.append(paint)
            group.append(layer)
        artwork.append(group)
    validate(root);write_svg(root,a.output)
    if a.line_art:
        if a.pencil_mode=='legacy':strokes=line_art(ink_mask,mapping,regions,w,h,a.line_art)
        else:
            from stroke_replay import make_lines
            strokes=make_lines(ink_mask,mapping,regions,w,h,a.line_art,plan.get('replay',{}))
    else:strokes=None
    report={'width':w,'height':h,'native_paths':path_count,'connected_contours':contour_count,'vertices':vertex_count,'pencil_strokes':strokes,'pencil_mode':a.pencil_mode,'svg_bytes':Path(a.output).stat().st_size,'region_coverage':coverage,'cleanup':cleanup,'palette_fingerprint':palette_id(palette),'plan_sha256':hashlib.sha256(Path(a.plan).read_bytes()).hexdigest(),'epsilon':a.epsilon,'overlap':a.overlap,'toolkit_version':VERSION,'merge_colors':a.merge_colors,'merged_color_indices':len(merged_colors),'limits':{'max_bytes':a.max_bytes,'max_paths':a.max_paths},'oversize':[],'note':'Appearance contours and reconstructed replay strokes are separate; visual QA is required.'}
    if a.max_paths>0 and path_count>a.max_paths:report['oversize'].append({'kind':'paths','value':path_count,'limit':a.max_paths})
    if a.max_bytes>0 and report['svg_bytes']>a.max_bytes:report['oversize'].append({'kind':'bytes','value':report['svg_bytes'],'limit':a.max_bytes})
    for item in report['oversize']:
        print(f"oversize: {item['kind']} {item['value']} exceeds limit {item['limit']}; discuss the fidelity/size tradeoff before delivering",file=sys.stderr)
    save_json(Path(a.work)/'trace-report.json',report);print(json.dumps(report,ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',action='version',version='img2svg '+VERSION)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('input');p.add_argument('--work',required=True);p.add_argument('--colors',type=int,default=80);p.add_argument('--denoise',type=float,default=12);p.add_argument('--seed',type=int,default=41);p.add_argument('--focus',action='append',default=[]);p.add_argument('--sample-step',type=int)
    p=sub.add_parser('trace');p.add_argument('--work',required=True);p.add_argument('--plan',required=True);p.add_argument('--output',required=True);p.add_argument('--line-art');p.add_argument('--epsilon',type=float,default=.55);p.add_argument('--overlap',type=float,default=1.4);p.add_argument('--pencil-mode',choices=['connected','legacy'],default='connected');p.add_argument('--max-bytes',type=int,default=0);p.add_argument('--max-paths',type=int,default=0);p.add_argument('--merge-colors',type=int,default=0)
    p=sub.add_parser('palette-merge');p.add_argument('work');p.add_argument('--from',dest='source',type=int,required=True);p.add_argument('--into',dest='target',type=int,required=True);p.add_argument('--plan');p.add_argument('--plan-out')
    p=sub.add_parser('draft-plan');p.add_argument('--work',required=True);p.add_argument('--output',required=True);p.add_argument('--min-area',type=int,default=12);p.add_argument('--epsilon',type=float,default=1.5);p.add_argument('--max-regions',type=int,default=0);p.add_argument('--ink-threshold',type=int,default=0)
    a=parser.parse_args()
    if a.command=='prepare':
        if not 1<=a.colors<=256 or a.denoise<0 or (a.sample_step is not None and a.sample_step<1):parser.error('colors 1..256; denoise >= 0; sample-step >= 1')
        prepare(a)
    elif a.command=='palette-merge':
        if a.source<0 or a.target<0:parser.error('palette indices must be >= 0')
        palette_merge(a)
    elif a.command=='draft-plan':
        if a.min_area<1 or not 0<=a.epsilon<=4 or a.max_regions<0 or not 0<=a.ink_threshold<=255:parser.error('draft-plan: min-area >= 1, 0 <= epsilon <= 4, max-regions >= 0, 0 <= ink-threshold <= 255')
        draft_plan(a)
    else:
        if not 0<=a.epsilon<=2 or not 0<=a.overlap<=3:parser.error('epsilon 0..2; overlap 0..3')
        if a.max_bytes<0 or a.max_paths<0 or a.merge_colors<0:parser.error('max-bytes/max-paths must be >= 0; 0 disables the limit; merge-colors >= 0')
        if not 0<=a.merge_colors<=60:parser.error('merge-colors must be 0..60')
        trace(a)
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
