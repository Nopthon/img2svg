"""Two-pass raster-reference to semantic native SVG. See references/plan-schema.md."""
import argparse, io, json, math, re, hashlib, sys
from pathlib import Path
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from PIL import Image, ImageOps, ImageCms
from svg_compat import NS, validate, write_svg
from version import VERSION
from state_files import replace_files
from quality import profile as quality_profile, resolve as resolve_fidelity

ET.register_namespace('',NS)
TONES=('background','color','shadow','highlight','detail','ink')
def node(name,attrs=None):return ET.Element('{'+NS+'}'+name,{k:str(v) for k,v in (attrs or {}).items()})
def save_json(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def color(c):return '#'+''.join(f'{int(v):02x}' for v in c)
def palette_id(palette):return hashlib.sha256(np.asarray(palette,dtype=np.uint8).tobytes()).hexdigest()
def despeckle_labels(labels,visible,min_area,palette,max_delta=45.0,passes=3):
    """Merge connected color islands smaller than min_area into the dominant nearby
    colour within max_delta RGB, so tiny antialias specks stop becoming contours."""
    labels=labels.copy();palette=palette.astype(np.float32)
    for _ in range(passes):
        changed=0
        for ci in np.unique(labels[visible]):
            m=np.uint8((labels==ci)&visible)
            count,components,stats,_=cv2.connectedComponentsWithStats(m,8)
            for i in range(1,count):
                if stats[i,cv2.CC_STAT_AREA]>=min_area:continue
                x,y,w,h,_=map(int,stats[i])
                x0,y0=max(0,x-1),max(0,y-1)
                x1,y1=min(labels.shape[1],x+w+1),min(labels.shape[0],y+h+1)
                local=labels[y0:y1,x0:x1]
                comp=components[y0:y1,x0:x1]==i
                ring=cv2.dilate(comp.astype(np.uint8),np.ones((3,3),np.uint8))
                near=local[(ring>0)&~comp&visible[y0:y1,x0:x1]];near=near[near!=ci]
                if not len(near):continue
                vals,counts=np.unique(near,return_counts=True)
                target=None
                for v in vals[np.argsort(-counts)]:
                    if float(np.linalg.norm(palette[ci]-palette[v]))<=max_delta:target=v;break
                if target is None:continue
                local[comp]=target;changed+=1
        if not changed:break
    return labels
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
    prof=quality_profile(a.fidelity)
    colors=a.colors if a.colors is not None else (prof['colors'] if prof else 80)
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
    k=min(colors,len(np.unique(sample,axis=0)))
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
    if prof and prof['label_min_area']>0:labels=despeckle_labels(labels,visible,prof['label_min_area'],palette)
    counts=np.bincount(labels[visible],minlength=k)
    for entry in entries:entry['pixels']=int(counts[entry['index']])
    reconstructed=np.dstack([palette[labels],alpha])
    Image.fromarray(reconstructed).save(work/'quantized-preview.png')
    np.savez_compressed(work/'prepared.npz',labels=labels,palette=palette,alpha=alpha)
    save_json(work/'palette.json',{'width':w,'height':h,'fingerprint':palette_id(palette),'colors':entries})
    report={'source':str(Path(a.input).resolve()),'source_sha256':hashlib.sha256(Path(a.input).read_bytes()).hexdigest(),'width':w,'height':h,'palette_size':k,'seed':a.seed,'denoise':a.denoise,'sample_step':step,'focus':a.focus,'fidelity':(prof['fidelity'] if prof else None),'label_min_area':(prof['label_min_area'] if prof else 0),'palette_fingerprint':palette_id(palette),'toolkit_version':VERSION,'opencv':cv2.__version__,'numpy':np.__version__,'has_transparency':bool((alpha<255).any()),'quantization_rgb_mae':float(np.abs(rgb.astype(float)-palette[labels].astype(float))[visible].mean())}
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
    if 'default' in plan:fix(plan['default'])
    for r in plan.get('regions',[]):fix(r)
    for r in plan.get('assignments',[]):fix(r)
    return plan

def palette_merge(a):
    """Validate and stage the complete merge before replacing any state files."""
    work=Path(a.work)
    with np.load(work/'prepared.npz',allow_pickle=False) as data:
        labels,palette,alpha=data['labels'],data['palette'],data['alpha']
    k=len(palette)
    if not 0<=a.source<k or not 0<=a.target<k:raise ValueError(f'Palette index out of range 0..{k-1}')
    if a.source==a.target:raise ValueError('--from and --into must differ')
    info=json.loads((work/'palette.json').read_text(encoding='utf-8'))
    old_fingerprint=palette_id(palette)
    if info['fingerprint']!=old_fingerprint:raise ValueError('Palette metadata does not match prepared data')
    entries={e['index']:e for e in info['colors']}
    if set(entries)!=set(range(k)) or len(info['colors'])!=k:raise ValueError('Invalid palette slots')
    counts=np.bincount(labels[alpha>0],minlength=k)
    for index in (a.source,a.target):
        if entries[index].get('merged_into') is not None or counts[index]==0:
            raise ValueError(f'Palette slot {index} is a tombstone or empty; merge live colors only')
    report_path=work/'prepare-report.json'
    report=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    plan=None;out_path=None
    if a.plan:
        plan_path=Path(a.plan)
        plan=json.loads(plan_path.read_text(encoding='utf-8-sig'))
        # Check source, indices, geometry and fingerprint against the old state.
        load_prepared(work,plan)
        out_path=Path(a.plan_out) if a.plan_out else plan_path
        reserved={work/name for name in ('prepared.npz','palette.json','prepare-report.json','quantized-preview.png')}
        if out_path.resolve() in {path.resolve() for path in reserved}:
            raise ValueError('Plan output must not overwrite prepared state')
    elif getattr(a,'plan_out',None):raise ValueError('--plan-out requires --plan')
    total=int(counts[a.target]+counts[a.source])
    merged=np.rint((palette[a.target].astype(float)*counts[a.target]+palette[a.source].astype(float)*counts[a.source])/total).astype(np.uint8)
    labels=labels.copy();labels[labels==a.source]=a.target
    palette=palette.copy();palette[a.target]=merged
    new_fingerprint=palette_id(palette)
    info['fingerprint']=new_fingerprint
    for e in info['colors']:
        e['pixels']=int(counts[e['index']])
        if e['index']==a.target:
            e['hex']=color(merged);e['rgb']=merged.tolist();e['pixels']=total
        elif e['index']==a.source:
            e['pixels']=0;e['merged_into']=a.target
    event={'from':a.source,'into':a.target,'merged_hex':color(merged),'previous_fingerprint':old_fingerprint,'toolkit_version':VERSION}
    report.setdefault('merges',[]).append(event)
    report['palette_fingerprint']=new_fingerprint
    if 'quantization_rgb_mae' in report:report['quantization_rgb_mae']=None
    plan_remapped=None
    json_bytes=lambda value:json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')
    files={}
    if plan is not None:
        remap_plan_indices(plan,a.source,a.target)
        plan['palette_fingerprint']=new_fingerprint
        plan_remapped=str(out_path.resolve());event['plan_remapped']=plan_remapped
        files[out_path]=json_bytes(plan)
    prepared=io.BytesIO();np.savez_compressed(prepared,labels=labels,palette=palette,alpha=alpha)
    preview=io.BytesIO();Image.fromarray(np.dstack([palette[labels],alpha])).save(preview,format='PNG')
    files.update({work/'prepared.npz':prepared.getvalue(),work/'quantized-preview.png':preview.getvalue(),work/'palette.json':json_bytes(info),report_path:json_bytes(report)})
    replace_files(files)
    print(json.dumps({'work':str(work.resolve()),'from':a.source,'into':a.target,'hex':color(merged),'pixels':total,'fingerprint':new_fingerprint,'plan_remapped':plan_remapped},ensure_ascii=False))


def draft_plan(a):
    """Draft exact palette masks; optional polygons support manual reshaping."""
    work=Path(a.work)
    with np.load(work/'prepared.npz',allow_pickle=False) as data:
        labels,palette,alpha=data['labels'],data['palette'],data['alpha']
    h,w=labels.shape;visible=alpha>0
    geometry=getattr(a,'geometry','masks')
    single=getattr(a,'single_region',False)
    counts=np.bincount(labels[visible],minlength=len(palette))
    regions=[];skipped=0
    for ci in ([] if single else np.flatnonzero(counts)):
        ci=int(ci);hexc=color(palette[ci])
        phase='ink' if a.ink_threshold>0 and int(max(palette[ci]))<a.ink_threshold else 'color'
        region={'id':f'palette-{ci}','name':f'Palette {ci} {hexc}','include_colors':[ci],'base':hexc,'phase':phase,'draft':{'pixels':int(counts[ci])}}
        if geometry=='masks':
            region['selector']='colors'
        else:
            m=np.uint8((labels==ci)&visible)
            count,cc,stats,_=cv2.connectedComponentsWithStats(m,8)
            polys=[]
            for k in range(1,count):
                if stats[k,cv2.CC_STAT_AREA]<a.min_area:continue
                x,y,bw,bh,_=map(int,stats[k])
                cs,_=cv2.findContours(np.uint8(cc[y:y+bh,x:x+bw]==k),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE,offset=(x,y))
                for c in cs:
                    if len(c)<3:continue
                    poly=cv2.approxPolyDP(c,a.epsilon,True).reshape(-1,2)
                    if len(poly)>=3:polys.append(poly.tolist())
            if not polys:skipped+=1;continue
            region['polygons']=polys
        regions.append(region)
    regions.sort(key=lambda r:-r['draft']['pixels'])
    if a.max_regions>0:regions=regions[:a.max_regions]
    dominant=color(palette[int(counts.argmax())])
    default={'id':'art' if single else 'unassigned','name':'Artwork' if single else 'Unassigned','base':dominant,'phase':'color'}
    plan={'title':'Auto draft plan','coordinate_size':[w,h],'palette_fingerprint':palette_id(palette),'default':default,'roles':{},'regions':regions,'draft_meta':{'generated_by':'img2svg draft-plan','toolkit_version':VERSION,'geometry':geometry,'single_region':single,'regions':len(regions),'skipped_colors':skipped,'note':'Palette masks are not semantic objects. Inspect the reference and group/split them, assign roles and protect important detail before optimization.'}}
    report_path=work/'prepare-report.json'
    if report_path.exists():
        source=json.loads(report_path.read_text(encoding='utf-8')).get('source_sha256')
        if source:plan['source_sha256']=source
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);save_json(out,plan)
    print(json.dumps({'draft_plan':str(out.resolve()),'regions':len(regions),'polygons':sum(len(r.get('polygons',[])) for r in regions),'skipped_colors':skipped,'width':w,'height':h},ensure_ascii=False))


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
        selector=r.get('selector')
        if selector is not None and (selector!='colors' or not r.get('include_colors') or 'polygon' in r or 'polygons' in r):
            raise ValueError('colors selector requires include_colors and no polygon: '+rid)
        polys=[] if selector=='colors' else r.get('polygons',[r.get('polygon',[])])
        mask=np.ones((h,w),np.uint8) if selector=='colors' else np.zeros((h,w),np.uint8)
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
        if 'polygon' in r or 'polygons' in r or 'selector' in r:apply_region(i,r)
    lookup={r['id']:i for i,r in enumerate(regions)}
    for assignment in plan.get('assignments',[]):
        if assignment.get('region') not in lookup:raise ValueError('Unknown assignment region')
        apply_region(lookup[assignment['region']],assignment)
    return regions,mapping

def load_prepared(work,plan):
    with np.load(Path(work)/'prepared.npz',allow_pickle=False) as data:
        labels,palette,alpha=data['labels'],data['palette'],data['alpha']
    fingerprint=palette_id(palette)
    metadata=Path(work)/'palette.json'
    if metadata.exists():
        info=json.loads(metadata.read_text(encoding='utf-8'))
        if info.get('fingerprint')!=fingerprint:
            raise ValueError('Palette metadata does not match prepared data')
        if not plan.get('palette_fingerprint'):
            raise ValueError('Plan palette_fingerprint is required for prepared palette data')
    prepared_report=Path(work)/'prepare-report.json'
    if plan.get('source_sha256'):
        report=json.loads(prepared_report.read_text(encoding='utf-8')) if prepared_report.exists() else {}
        if report.get('source_sha256')!=plan['source_sha256']:raise ValueError('Plan source_sha256 belongs to a different source image')
    if plan.get('palette_fingerprint') and plan['palette_fingerprint']!=fingerprint:
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

def collapse_palette(labels,palette,plan,distance,alpha,regions,mapping,max_diameter=None):
    """Merge visible colours only within the same region and resolved role.

    Paint overrides are keyed by (region, representative), since the same
    palette index can have different meanings and mixtures in different regions.
    """
    out=labels.copy();paint={};merged_count=0;k=len(palette)
    for ri,region in enumerate(regions):
        threshold=region.get('trace',{}).get('merge_colors',distance)
        if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not 0<=threshold<=60:
            raise ValueError('Regional merge_colors must be within 0..60')
        if max_diameter is not None:threshold=min(threshold,max_diameter)
        if threshold==0:continue
        owned=(mapping==ri)&(alpha>0)
        counts=np.bincount(labels[owned],minlength=k)
        live=np.flatnonzero(counts).tolist()
        roles={ci:role_for(region,ci,plan.get('roles',{})) for ci in live}
        # Complete-link groups bound the entire colour diameter: a chain of
        # individually close shades must not collapse unrelated endpoints.
        groups=[]
        rgb=palette.astype(float)
        for ci in sorted(live,key=lambda index:(-counts[index],index)):
            choices=[]
            for index,members in enumerate(groups):
                if roles[ci]!=roles[members[0]]:continue
                if np.max(np.linalg.norm(rgb[members]-rgb[ci],axis=1))>threshold:continue
                mean=np.average(rgb[members],axis=0,weights=counts[members])
                choices.append((float(np.linalg.norm(rgb[ci]-mean)),index))
            if choices:groups[min(choices)[1]].append(ci)
            else:groups.append([ci])
        lookup=np.arange(k,dtype=labels.dtype)
        for members in groups:
            if len(members)<2:continue
            rep=max(members,key=lambda ci:counts[ci])
            mean=np.rint(np.average(palette[members].astype(float),axis=0,weights=counts[members])).astype(np.uint8)
            lookup[members]=rep;paint[ri,rep]=color(mean)
            merged_count+=len(members)-1
        out[owned]=lookup[labels[owned]]
    return out,paint,merged_count


def auto_tone_source(work,plan,shape):
    """Only trusted, single-region auto plans may sample their original image."""
    if not plan.get('draft_meta',{}).get('single_region'):return None,'semantic plan'
    report=Path(work)/'prepare-report.json'
    if not report.exists():return None,'prepare report unavailable'
    info=json.loads(report.read_text(encoding='utf-8'))
    path=Path(info.get('source',''))
    if not path.is_file():return None,'original source unavailable'
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=info.get('source_sha256') or (plan.get('source_sha256') and digest!=plan['source_sha256']):
        return None,'original source hash mismatch'
    rgba=image_rgba(path)
    if rgba.shape[:2]!=shape:return None,'original source dimensions differ'
    return rgba[:,:,:3],'verified original source'


def path_data(points):
    """Short SVG commands with exact quarter-pixel coordinates (no rounding)."""
    points=np.asarray(points).reshape(-1,2).astype(float)/2+.25
    def number(value):
        text=format(value,'.2f').rstrip('0').rstrip('.')
        if text.startswith('0.'):return text[1:]
        if text.startswith('-0.'):return '-'+text[2:]
        return text
    def pair(x,y):
        a,b=number(x),number(y)
        return a+('' if b.startswith('-') else ' ')+b
    parts=['M'+pair(*points[0])];previous=points[0];last='M'
    for point in points[1:]:
        dx,dy=point-previous
        if dx==0:choices=[('v',number(dy)),('V',number(point[1]))]
        elif dy==0:choices=[('h',number(dx)),('H',number(point[0]))]
        else:choices=[('l',pair(dx,dy)),('L',pair(*point))]
        candidates=[]
        for command,args in choices:
            prefix=('' if args.startswith('-') else ' ') if command==last else command
            candidates.append((prefix+args,command))
        segment,last=min(candidates,key=lambda item:len(item[0]))
        parts.append(segment);previous=point
    return ''.join(parts)+'Z'


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



def trace(a):
    plan=json.loads(Path(a.plan).read_text(encoding='utf-8-sig'))
    labels,palette,alpha,regions,mapping=load_prepared(a.work,plan);h,w=labels.shape
    from region_cleanup import clean_regions
    labels,cleanup=clean_regions(labels,palette,alpha,mapping,regions,plan.get('roles',{}))
    auto_plan=bool(plan.get('draft_meta',{}).get('single_region'))
    protect=auto_plan and not getattr(a,'no_weak_tones',False)
    # Guard against merging pigments sampled from unrelated locations. The
    # merged group may otherwise darken a faint patch and lighten its surround.
    max_diameter=(12-.04*quality_profile(getattr(a,'fidelity',None))['fidelity']) if protect else None
    labels,paint_override,merged_count=collapse_palette(labels,palette,plan,a.merge_colors,alpha,regions,mapping,max_diameter=max_diameter)
    source_rgb,source_status=auto_tone_source(a.work,plan,(h,w)) if protect else (None,'disabled')
    from weak_tones import separate_weak_tones,gradient_for_component,vector_gradient_rings
    tone_count=tone_pixels=gradient_count=0
    root=node('svg',{'id':'illustration','version':'1.1','width':w,'height':h,'viewBox':f'0 0 {w} {h}','preserveAspectRatio':'xMidYMid meet'})
    title=node('title');title.text=plan.get('title','Reference reconstruction');root.append(title)
    if np.all(alpha==255):
        # An opaque raster has no transparent cracks, including at fitted edges.
        background=int(np.bincount(labels.ravel(),minlength=len(palette)).argmax())
        root.append(node('rect',{'id':'drawing-paper','width':w,'height':h,'fill':color(palette[background]),'stroke':'none'}))
    artwork=node('g',{'id':'artwork'});root.append(artwork)
    vertex_count=contour_count=path_count=0;coverage=[]
    packed=labels.astype(np.uint32)*256+alpha.astype(np.uint32)
    for ri,r in enumerate(regions):
        group=node('g',{'id':r['id'],'data-region':r['id'],'data-name':r.get('name',r['id']),'data-base':r['base']})
        covered=(mapping==ri)&(alpha>0);coverage.append({'id':r['id'],'pixels':int(covered.sum())})
        if not covered.any():continue
        pigment={tone:[] for tone in TONES}
        for code in np.unique(packed[covered]):
            ci=int(code)//256;opacity=int(code)%256
            role=role_for(r,ci,plan.get('roles',{}));m=(mapping==ri)&(packed==code)
            settings=r.get('trace',{});epsilon=settings.get('epsilon',a.epsilon)
            if 'dark_epsilon' in settings and max(palette[ci])<settings.get('dark_threshold',176):epsilon=settings['dark_epsilon']
            overlap=settings.get('overlap',a.overlap)
            if not 0<=epsilon<=2 or not 0<=overlap<=3:raise ValueError('Invalid regional trace settings')
            width=.55 if role=='ink' or opacity<255 else overlap
            paint=paint_override.get((ri,ci),color(palette[ci]))
            masks=[(np.uint8(m)*255,paint,None)]
            if source_rgb is not None and role=='color' and opacity==255:
                original=np.array([int(paint[i:i+2],16) for i in (1,3,5)],np.uint8)
                remaining,parts,affected=separate_weak_tones(masks[0][0],source_rgb,original,max_area=max(160,int(h*w*.04)))
                masks=[(remaining,paint,None)]
                for component,rgb in parts:
                    gradient=(gradient_for_component(component,source_rgb,rgb)
                              if getattr(a,'soft_tones_mode','gradient')=='gradient' else None)
                    masks.append((component,color(rgb),gradient))
                tone_count+=len(parts);tone_pixels+=affected
            for number,(part_mask,part_paint,gradient) in enumerate(masks):
                if not part_mask.any():continue
                suffix=f'-tone{number}' if number else ''
                if gradient is not None:
                    group_id=f'{r["id"]}-{role}-c{ci}-a{opacity}{suffix}'
                    bands=node('g',{'id':group_id,'data-soft-tone':'vector-gradient'})
                    budget=int(round(10+10*quality_profile(getattr(a,'fidelity',None))['fidelity']/100))
                    for bi,(local,stop_rgb,x0,y0) in enumerate(vector_gradient_rings(part_mask,gradient,budget)):
                        d,v,c=contours_to_path(local,epsilon)
                        if not d:continue
                        bands.append(node('path',{'id':f'{group_id}-band{bi}','d':d,
                            'transform':f'translate({x0} {y0})',
                            'fill':color(stop_rgb),'stroke':'none','fill-rule':'evenodd'}))
                        vertex_count+=v;contour_count+=c;path_count+=1
                    if len(bands):
                        pigment[role].append((float(palette[ci].mean()),bands))
                        gradient_count+=1
                    continue
                d,vertices,contours=contours_to_path(part_mask,min(epsilon,.2) if opacity<255 else epsilon)
                if not d:continue
                attrs={'id':f'{r["id"]}-{role}-c{ci}-a{opacity}{suffix}','fill':part_paint,'stroke':part_paint,'stroke-width':f'{width:g}','stroke-linejoin':'round','stroke-linecap':'round','fill-rule':'evenodd','d':d}
                if opacity<255:attrs['opacity']=f'{opacity/255:.6f}'
                pigment[role].append((float(palette[ci].mean()),node('path',attrs)))
                vertex_count+=vertices;contour_count+=contours;path_count+=1
        for tone in TONES:
            if not pigment[tone]:continue
            layer=node('g',{'id':f'{r["id"]}-{tone}','data-tone':tone})
            for _,paint in sorted(pigment[tone],key=lambda v:-v[0]):layer.append(paint)
            group.append(layer)
        artwork.append(group)
    validate(root)
    svg_buffer=io.BytesIO()
    ET.ElementTree(root).write(svg_buffer,encoding='utf-8',xml_declaration=True)
    svg_bytes=svg_buffer.getvalue()
    outputs={Path(a.output):svg_bytes}
    report={'width':w,'height':h,'native_paths':path_count,'connected_contours':contour_count,'vertices':vertex_count,'svg_bytes':len(svg_bytes),'region_coverage':coverage,'cleanup':cleanup,'palette_fingerprint':palette_id(palette),'plan_sha256':hashlib.sha256(Path(a.plan).read_bytes()).hexdigest(),'epsilon':a.epsilon,'overlap':a.overlap,'toolkit_version':VERSION,'fidelity':getattr(a,'fidelity',None),'merge_colors':a.merge_colors,'merged_color_indices':merged_count,'weak_tones':{'enabled':protect,'source':source_status,'max_merge_diameter':max_diameter,'recolored_components':tone_count,'recolored_pixels':tone_pixels,'gradient_components':gradient_count},'limits':{'max_bytes':a.max_bytes,'max_paths':a.max_paths},'oversize':[],'note':'Visual quality assessment requires independent rendering and image inspection.'}
    if a.max_paths>0 and path_count>a.max_paths:report['oversize'].append({'kind':'paths','value':path_count,'limit':a.max_paths})
    if a.max_bytes>0 and report['svg_bytes']>a.max_bytes:report['oversize'].append({'kind':'bytes','value':report['svg_bytes'],'limit':a.max_bytes})
    for item in report['oversize']:
        print(f"oversize: {item['kind']} {item['value']} exceeds limit {item['limit']}; discuss the fidelity/size tradeoff before delivering",file=sys.stderr)
    outputs[Path(getattr(a,'report',None) or Path(a.work)/'trace-report.json')]=json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8')
    replace_files(outputs)
    print(json.dumps(report,ensure_ascii=False))

def auto(a):
    """One-click, agent-free pipeline: prepare -> draft-plan -> trace.
    A single --fidelity value drives every stage's fidelity/size tradeoff."""
    prof=quality_profile(a.fidelity)
    out=Path(a.output);work=Path(a.work) if a.work else out/'work'
    prepare(argparse.Namespace(input=a.input,work=str(work),colors=None,denoise=12,seed=41,focus=[],sample_step=None,fidelity=a.fidelity))
    draft_plan(argparse.Namespace(work=str(work),output=str(work/'plan.json'),min_area=max(4,prof['label_min_area']),epsilon=prof['epsilon'],max_regions=0,ink_threshold=0,geometry='masks',single_region=True))
    trace(argparse.Namespace(work=str(work),plan=str(work/'plan.json'),output=str(out/'illustration.svg'),epsilon=prof['epsilon'],overlap=prof['overlap'],max_bytes=a.max_bytes,max_paths=a.max_paths,merge_colors=prof['merge_distance'],fidelity=prof['fidelity'],no_weak_tones=getattr(a,'no_weak_tones',False),soft_tones_mode=getattr(a,'soft_tones_mode','gradient')))
    print(json.dumps({'auto':str(out.resolve()),'work':str(work.resolve()),'fidelity':prof['fidelity'],'colors':prof['colors'],'epsilon':prof['epsilon'],'merge_distance':prof['merge_distance']},ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',action='version',version='img2svg '+VERSION)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('input');p.add_argument('--work',required=True);p.add_argument('--colors',type=int);p.add_argument('--denoise',type=float,default=12);p.add_argument('--seed',type=int,default=41);p.add_argument('--focus',action='append',default=[]);p.add_argument('--sample-step',type=int);p.add_argument('--fidelity')
    p=sub.add_parser('trace');p.add_argument('--work',required=True);p.add_argument('--plan',required=True);p.add_argument('--output',required=True);p.add_argument('--epsilon',type=float);p.add_argument('--overlap',type=float);p.add_argument('--report');p.add_argument('--max-bytes',type=int,default=0);p.add_argument('--max-paths',type=int,default=0);p.add_argument('--merge-colors',type=int);p.add_argument('--fidelity');p.add_argument('--no-weak-tones',action='store_true',help='Disable conservative weak-tone preservation for agent-free plans');p.add_argument('--soft-tones-mode',choices=['gradient','recolor'],default='gradient')
    p=sub.add_parser('palette-merge');p.add_argument('work');p.add_argument('--from',dest='source',type=int,required=True);p.add_argument('--into',dest='target',type=int,required=True);p.add_argument('--plan');p.add_argument('--plan-out')
    p=sub.add_parser('draft-plan');p.add_argument('--work',required=True);p.add_argument('--output',required=True);p.add_argument('--min-area',type=int,default=12);p.add_argument('--epsilon',type=float,default=1.5);p.add_argument('--max-regions',type=int,default=0);p.add_argument('--ink-threshold',type=int,default=0);p.add_argument('--geometry',choices=['masks','polygons'],default='masks')
    p=sub.add_parser('auto');p.add_argument('input');p.add_argument('--output',required=True);p.add_argument('--work');p.add_argument('--fidelity',default='balanced');p.add_argument('--max-bytes',type=int,default=0);p.add_argument('--max-paths',type=int,default=0);p.add_argument('--no-weak-tones',action='store_true',help='Disable source-aware weak-tone preservation');p.add_argument('--soft-tones-mode',choices=['gradient','recolor'],default='gradient')
    a=parser.parse_args()
    if a.command=='prepare':
        if a.colors is not None and not 1<=a.colors<=256:parser.error('colors 1..256')
        if a.denoise<0 or (a.sample_step is not None and a.sample_step<1):parser.error('denoise >= 0; sample-step >= 1')
        if a.fidelity is not None:resolve_fidelity(a.fidelity)
        prepare(a)
    elif a.command=='palette-merge':
        if a.source<0 or a.target<0:parser.error('palette indices must be >= 0')
        palette_merge(a)
    elif a.command=='draft-plan':
        if a.min_area<1 or not 0<=a.epsilon<=4 or a.max_regions<0 or not 0<=a.ink_threshold<=255:parser.error('draft-plan: min-area >= 1, 0 <= epsilon <= 4, max-regions >= 0, 0 <= ink-threshold <= 255')
        draft_plan(a)
    elif a.command=='auto':
        if a.max_bytes<0 or a.max_paths<0:parser.error('max-bytes/max-paths must be >= 0; 0 disables the limit')
        auto(a)
    else:
        prof=quality_profile(a.fidelity)
        if a.epsilon is None:a.epsilon=prof['epsilon']
        if a.overlap is None:a.overlap=prof['overlap']
        if a.merge_colors is None:a.merge_colors=prof['merge_distance']
        a.fidelity=prof['fidelity']
        if not 0<=a.epsilon<=2 or not 0<=a.overlap<=3:parser.error('epsilon 0..2; overlap 0..3')
        if not 0<=a.merge_colors<=60:parser.error('merge-colors must be 0..60')
        if a.max_bytes<0 or a.max_paths<0:parser.error('max-bytes/max-paths must be >= 0; 0 disables the limit')
        trace(a)
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
