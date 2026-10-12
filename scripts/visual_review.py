"""Generate inspectable evidence, not an automatic certificate of visual fidelity.
All PNGs are scratch analysis artifacts; never embed them in delivered SVG.
"""
import argparse,hashlib,io,json,math,re,sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw
from vectorize import image_rgba,load_prepared,role_for,TONES,save_json
from version import VERSION

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def white(rgba):
    a=rgba[:,:,3:4].astype(float)/255
    return np.uint8(np.round(rgba[:,:,:3]*a+255*(1-a)))
def preview(array,width=1100):
    im=Image.fromarray(array);im.thumbnail((width,1600),Image.Resampling.LANCZOS);return im
def caption(im,title):
    result=Image.new('RGB',(im.width,im.height+25),'white');result.paste(im,(0,25))
    ImageDraw.Draw(result).text((6,6),title,fill='black');return result
def panel(images,titles,width=640,upscale=False):
    views=[]
    for array,title in zip(images,titles):
        im=preview(array,width)
        if upscale:
            scale=min(3,width/im.width,800/im.height)
            if scale>1:im=im.resize((round(im.width*scale),round(im.height*scale)),Image.Resampling.NEAREST)
        views.append(caption(im,title))
    result=Image.new('RGB',(sum(v.width for v in views),max(v.height for v in views)),'#eeeeee')
    x=0
    for view in views:result.paste(view,(x,0));x+=view.width
    return result
def roi_list(plan,w,h,extra):
    cw,ch=plan.get('coordinate_size',[w,h]);result=[]
    for item in plan.get('checkpoints',[]):
        x,y,bw,bh=item['box'];result.append({'id':item['id'],'box':[round(x*w/cw),round(y*h/ch),round(bw*w/cw),round(bh*h/ch)],'critical':item.get('critical',True)})
    for roi in extra:
        name,box=roi.split(':',1);result.append({'id':name,'box':[int(n) for n in box.split(',')],'critical':True})
    seen=set()
    for item in result:
        if not re.fullmatch('[a-z][a-z0-9-]*',item['id']) or item['id'] in seen:raise ValueError('Unique ASCII checkpoint id required')
        seen.add(item['id']);x,y,bw,bh=item['box']
        if min(x,y)<0 or min(bw,bh)<=0 or x+bw>w or y+bh>h:raise ValueError('Checkpoint outside original image: '+item['id'])
    return result

def inspect(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    rgba=image_rgba(a.reference);rgb=white(rgba);h,w=rgb.shape[:2]
    overview=preview(rgb);draw=ImageDraw.Draw(overview);sx=overview.width/w;sy=overview.height/h;tiles=[]
    if a.tile_size<128:raise ValueError('tile-size must be >= 128')
    for y in range(0,h,a.tile_size):
        for x in range(0,w,a.tile_size):
            x1=min(w,x+a.tile_size);y1=min(h,y+a.tile_size);name=f'tile-{len(tiles)+1:03d}'
            file=out/(name+'.png');caption(Image.fromarray(rgb[y:y1,x:x1]),f'{name} original pixels x={x} y={y}').save(file)
            draw.rectangle((x*sx,y*sy,(x1-1)*sx,(y1-1)*sy),outline='#bd3568',width=2)
            draw.text((x*sx+4,y*sy+4),name,fill='#bd3568',stroke_width=1,stroke_fill='white')
            tiles.append({'id':name,'box':[x,y,x1-x,y1-y],'file':str(file.resolve())})
    overview.save(out/'overview-grid.png')
    rois=roi_list({},w,h,a.roi)
    for r in rois:
        x,y,bw,bh=r['box'];caption(Image.fromarray(rgb[y:y+bh,x:x+bw]),r['id']).save(out/(r['id']+'.png'))
    save_json(out/'inspection.json',{'source_sha256':sha(a.reference),'size':[w,h],'orientation':'EXIF normalized','alpha_present':bool((rgba[:,:,3]<255).any()),'overview':str((out/'overview-grid.png').resolve()),'tiles':tiles,'requested_crops':rois,'toolkit_version':VERSION,'instruction':'Open overview and relevant crops through an image-capable tool. File paths alone are not visual access.'})
    print(json.dumps({'inspection':str(out/'inspection.json'),'tiles':len(tiles)}))

def plan_review(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    plan=json.loads(Path(a.plan).read_text(encoding='utf-8-sig'))
    labels,palette,alpha,regions,mapping=load_prepared(a.work,plan);h,w=labels.shape
    rgba=image_rgba(a.reference)
    if rgba.shape[:2]!=(h,w):raise ValueError('Reference dimensions differ from prepared data')
    prep=Path(a.work)/'prepare-report.json'
    if prep.exists() and json.loads(prep.read_text(encoding='utf-8')).get('source_sha256') not in (None,sha(a.reference)):raise ValueError('Prepared palette belongs to another reference')
    rgb=white(rgba);rng=np.random.default_rng(91);colors=rng.integers(35,230,(len(regions),3),dtype=np.uint8)
    overlay=np.uint8(rgb*.64+colors[mapping]*.36);overlay[alpha==0]=255
    boundary=np.zeros((h,w),bool);boundary[:,1:]|=mapping[:,1:]!=mapping[:,:-1];boundary[1:,:]|=mapping[1:,:]!=mapping[:-1,:]
    overlay[boundary]=[206,46,111]
    annotated=Image.fromarray(overlay);draw=ImageDraw.Draw(annotated)
    role_colors=np.array([[244,235,220],[137,183,120],[77,105,148],[250,216,79],[203,104,165],[49,47,57]],np.uint8)
    roles=np.zeros((h,w),np.uint8);reports=[]
    for ri,r in enumerate(regions):
        owned=(mapping==ri)&(alpha>0);ys,xs=np.where(owned);pixels=int(owned.sum());small=0;total=0;tiny_pixels=0;roles_count={}
        if pixels:
            d=cv2.distanceTransform(owned.astype(np.uint8),cv2.DIST_L2,3);cy,cx=np.unravel_index(d.argmax(),d.shape)
            draw.text((int(cx),int(cy)),f'{ri}: {r["id"]}',fill='black',stroke_width=2,stroke_fill='white')
        for ci in np.unique(labels[owned]):
            selected=owned&(labels==ci);role=role_for(r,int(ci),plan.get('roles',{}));roles[selected]=TONES.index(role)
            roles_count[role]=roles_count.get(role,0)+int(selected.sum())
            count,_,stats,_=cv2.connectedComponentsWithStats(selected.astype(np.uint8),8)
            areas=stats[1:,cv2.CC_STAT_AREA];small+=int((areas<=4).sum());total+=count-1;tiny_pixels+=int(areas[areas<=4].sum())
        reports.append({'number':ri,'id':r['id'],'pixels':pixels,'frame_fraction':pixels/(h*w),'pigment_components':total,'components_area_le4':small,'pixels_in_small_components':tiny_pixels,'roles':roles_count})
    annotated.save(out/'regions-full.png');preview(np.array(annotated)).save(out/'regions-overview.png')
    role_image=role_colors[roles];role_image[alpha==0]=255;Image.fromarray(role_image).save(out/'roles-full.png')
    swatches=Image.new('RGB',(8*150,math.ceil(len(palette)/8)*65),'white');sd=ImageDraw.Draw(swatches)
    for i,c in enumerate(palette):
        x=(i%8)*150;y=(i//8)*65;sd.rectangle((x+3,y+3,x+48,y+53),fill=tuple(map(int,c)))
        sd.text((x+53,y+8),f'{i}: #'+''.join(f'{v:02x}' for v in c),fill='black');sd.text((x+53,y+28),f'{int(((labels==i)&(alpha>0)).sum())} px',fill='black')
    swatches.save(out/'palette-atlas.png')
    for roi in roi_list(plan,w,h,a.roi):
        x,y,bw,bh=roi['box'];panel([rgb[y:y+bh,x:x+bw],np.array(annotated)[y:y+bh,x:x+bw],role_image[y:y+bh,x:x+bw]],['Reference','Ownership','Pigment roles'],420,True).save(out/(roi['id']+'-plan.png'))
    save_json(out/'plan-report.json',{'plan_sha256':sha(a.plan),'toolkit_version':VERSION,'regions':reports,'role_legend':{role:'#'+''.join(f'{v:02x}' for v in c) for role,c in zip(TONES,role_colors)},'warnings':['Empty region: '+r['id'] for r in reports if not r['pixels']],'note':'Small components are diagnostic, not automatically noise. Inspect ownership and roles before cleanup.'})
    print(json.dumps({'plan_report':str(out/'plan-report.json'),'regions':len(reports),'small_components':sum(r['components_area_le4'] for r in reports)}))

def _srgb_to_lab(rgb):
    c=rgb.astype(np.float64)/255
    c=np.where(c<=0.04045,c/12.92,((c+0.055)/1.055)**2.4)
    m=np.array([[0.4124564,0.3575761,0.1804375],[0.2126729,0.7151522,0.0721750],[0.0193339,0.1191920,0.9503041]])
    xyz=(c@m.T)/np.array([0.95047,1.0,1.08883])
    f=np.where(xyz>0.008856,np.cbrt(xyz),7.787*xyz+16/116)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)

def _ciede2000(lab1,lab2):
    L1,a1,b1=lab1[...,0],lab1[...,1],lab1[...,2];L2,a2,b2=lab2[...,0],lab2[...,1],lab2[...,2]
    C1=np.hypot(a1,b1);C2=np.hypot(a2,b2);Cbar=(C1+C2)/2
    G=0.5*(1-np.sqrt(Cbar**7/(Cbar**7+25**7+1e-30)))
    a1p=(1+G)*a1;a2p=(1+G)*a2
    C1p=np.hypot(a1p,b1);C2p=np.hypot(a2p,b2)
    h1p=np.degrees(np.arctan2(b1,a1p))%360;h2p=np.degrees(np.arctan2(b2,a2p))%360
    dLp=L2-L1;dCp=C2p-C1p;dhp=h2p-h1p
    dhp=np.where(dhp>180,dhp-360,np.where(dhp<-180,dhp+360,dhp));dhp=np.where(C1p*C2p==0,0,dhp)
    dHp=2*np.sqrt(C1p*C2p)*np.sin(np.radians(dhp/2))
    Lbar=(L1+L2)/2;Cbarp=(C1p+C2p)/2;hsum=h1p+h2p
    hbarp=np.where(C1p*C2p==0,hsum,np.where(np.abs(h1p-h2p)<=180,hsum/2,np.where(hsum<360,(hsum+360)/2,(hsum-360)/2)))
    T=1-0.17*np.cos(np.radians(hbarp-30))+0.24*np.cos(np.radians(2*hbarp))+0.32*np.cos(np.radians(3*hbarp+6))-0.20*np.cos(np.radians(4*hbarp-63))
    dtheta=30*np.exp(-((hbarp-275)/25)**2);Rc=2*np.sqrt(Cbarp**7/(Cbarp**7+25**7+1e-30))
    Sl=1+(0.015*(Lbar-50)**2)/np.sqrt(20+(Lbar-50)**2);Sc=1+0.045*Cbarp;Sh=1+0.015*Cbarp*T
    Rt=-np.sin(np.radians(2*dtheta))*Rc
    return np.sqrt((dLp/Sl)**2+(dCp/Sc)**2+(dHp/Sh)**2+Rt*(dCp/Sc)*(dHp/Sh))

def metrics(ref,out):
    rgb1,rgb2=white(ref),white(out);delta=np.abs(rgb1.astype(float)-rgb2.astype(float))
    e1=cv2.Canny(rgb1,60,140)>0;e2=cv2.Canny(rgb2,60,140)>0;k=np.ones((5,5),np.uint8)
    recall=float((e1&(cv2.dilate(e2.astype('uint8'),k)>0)).sum()/e1.sum()) if e1.any() else 1.
    precision=float((e2&(cv2.dilate(e1.astype('uint8'),k)>0)).sum()/e2.sum()) if e2.any() else 1.
    lab1=_srgb_to_lab(rgb1);lab2=_srgb_to_lab(rgb2);de=_ciede2000(lab1,lab2)
    cast=(lab2-lab1).reshape(-1,3).mean(axis=0)
    black1=ref[:,:,:3].astype(float)*(ref[:,:,3:4]/255.)
    black2=out[:,:,:3].astype(float)*(out[:,:,3:4]/255.)
    return {'rgb_mae_white':float(delta.mean()),'rgb_mae_black':float(np.abs(black1-black2).mean()),'rgb_p95_white':float(np.percentile(delta,95)),'alpha_mae':float(np.abs(ref[:,:,3].astype(float)-out[:,:,3].astype(float)).mean()),'edge_recall_2px':recall,'edge_precision_2px':precision,'lab_delta_e00_mean':float(de.mean()),'lab_delta_e00_p95':float(np.percentile(de,95)),'lab_cast':{'dL':float(cast[0]),'da':float(cast[1]),'db':float(cast[2])}}

def render_svg(svg,width=None,height=None):
    """Shared independent renderer; never stretch away a geometry defect."""
    try:
        import pymupdf
    except ImportError:
        raise SystemExit('pymupdf is not installed; run pip install -r requirements-render.txt before visual comparison')
    from svg_compat import load_svg,validate
    info=validate(load_svg(svg));vw,vh=info['viewBox'][2:]
    if width is not None and width<=0:raise ValueError('Render width must be positive')
    if height is not None and (width is None or height<=0 or abs(vw/vh-width/height)>1e-5):
        raise ValueError('SVG aspect ratio differs; do not resize away a geometry defect')
    with pymupdf.open(svg) as doc:
        page=doc[0]
        scale=width/page.rect.width if width is not None else 1
        scale_y=height/page.rect.height if height is not None else scale
        pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale_y),alpha=True)
        actual=np.array(Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGBA'))
    return actual,info,'MuPDF '+pymupdf.VersionBind

def compare(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    ref=image_rgba(a.reference);h,w=ref.shape[:2]
    actual,info,renderer=render_svg(a.svg,w,h)
    if actual.shape!=ref.shape:raise ValueError('Renderer dimensions differ from reference')
    Image.fromarray(actual).save(out/'render.png');rgb1,rgb2=white(ref),white(actual)
    error=np.abs(rgb1.astype(float)-rgb2.astype(float)).mean(axis=2)
    heat=np.uint8(np.clip(error*6,0,255));heat=np.dstack([heat,np.zeros_like(heat),np.zeros_like(heat)])
    panel([rgb1,rgb2,heat],['Reference','Rendered SVG','Difference x6'],500).save(out/'overview-comparison.png')
    plan=json.loads(Path(a.plan).read_text(encoding='utf-8-sig')) if a.plan else {}
    rois=roi_list(plan,w,h,a.roi)
    # Include high-error locations even when the model overlooks a semantic feature.
    boxes=[];tile=256
    for y in range(0,h,tile):
        for x in range(0,w,tile):boxes.append((float(error[y:y+tile,x:x+tile].mean()),x,y,min(tile,w-x),min(tile,h-y)))
    for i,(_,x,y,bw,bh) in enumerate(sorted(boxes,reverse=True)[:4]):rois.append({'id':f'auto-error-{i+1}','box':[x,y,bw,bh],'critical':False})
    crops=[]
    for r in rois:
        x,y,bw,bh=r['box'];file=out/(r['id']+'-comparison.png')
        panel([rgb1[y:y+bh,x:x+bw],rgb2[y:y+bh,x:x+bw],heat[y:y+bh,x:x+bw]],['Reference','SVG','Difference x6'],640,True).save(file)
        crops.append(dict(r,file=str(file.resolve()),metrics=metrics(ref[y:y+bh,x:x+bw],actual[y:y+bh,x:x+bw])))
    report={'source_sha256':sha(a.reference),'svg_sha256':sha(a.svg),'plan_sha256':sha(a.plan) if a.plan else None,'renderer':renderer,'toolkit_version':VERSION,'size':[w,h],'global':metrics(ref,actual),'crops':crops,'structural':info,'quality_pass':None,'note':'Metrics locate differences; a blurred or fragmented image can still score well. Inspect crops before claiming fidelity.'}
    save_json(out/'comparison.json',report)
    draft={'image_access':'unconfirmed','svg_sha256':sha(a.svg),'inspected_images':[],'checks':[{'id':'whole-composition','critical':True,'status':'pending','observation':''}]+[{'id':r['id'],'critical':r['critical'],'status':'pending','observation':''} for r in rois],'repairs':[],'limitations':[]}
    save_json(out/'review-template.json',draft)
    print(json.dumps({'comparison':str(out/'comparison.json'),'global':report['global'],'crops':len(crops)}))

def candidate_failures(report,max_mae,max_alpha_mae,min_edge_recall):
    """Numerical screening applies independently to every critical crop."""
    failures=[]
    checks=[('whole-composition',report['global'])]
    checks += [(crop['id'],crop['metrics']) for crop in report['crops'] if crop['critical']]
    for name,m in checks:
        if max(m['rgb_mae_white'],m['rgb_mae_black'])>max_mae:failures.append(name+': colour error')
        if m['alpha_mae']>max_alpha_mae:failures.append(name+': alpha error')
        if m['edge_recall_2px']<min_edge_recall:failures.append(name+': lost edges')
    return failures

def candidates(a):
    """Build a bounded comparison set for an image-capable agent to choose from."""
    import argparse
    import contextlib
    from vectorize import trace
    from quality import profile
    # Fail before touching the output if rendering, inputs or parameters are invalid.
    import pymupdf
    profiles=[profile(value.strip()) for value in a.fidelities.split(',')]
    if not 1<=len(profiles)<=5:raise ValueError('Choose 1..5 fidelity candidates')
    if len({p['fidelity'] for p in profiles})!=len(profiles):raise ValueError('Duplicate fidelity candidates')
    if not (math.isfinite(a.max_mae) and a.max_mae>=0 and math.isfinite(a.max_alpha_mae) and a.max_alpha_mae>=0 and 0<=a.min_edge_recall<=1 and a.max_bytes>=0):
        raise ValueError('Invalid candidate limits')
    plan=json.loads(Path(a.plan).read_text(encoding='utf-8-sig'))
    labels,_,_,_,_=load_prepared(a.work,plan)
    ref=image_rgba(a.reference)
    if ref.shape[:2]!=labels.shape:raise ValueError('Reference dimensions differ from prepared data')
    prep=Path(a.work)/'prepare-report.json'
    if prep.exists() and json.loads(prep.read_text(encoding='utf-8')).get('source_sha256') not in (None,sha(a.reference)):
        raise ValueError('Prepared data belongs to another reference')
    rois=roi_list(plan,ref.shape[1],ref.shape[0],[])
    out=Path(a.output)
    if out.exists() and any(out.iterdir()):raise ValueError('Use a fresh candidate output directory to preserve previous evidence')
    out.mkdir(parents=True,exist_ok=True)
    items=[];views=[white(ref)];titles=['Reference']
    for prof in profiles:
        identity='f'+format(prof['fidelity'],'g')
        folder=out/identity;folder.mkdir()
        svg=folder/'illustration.svg'
        args=argparse.Namespace(work=a.work,plan=a.plan,output=svg,max_bytes=a.max_bytes,max_paths=0,report=folder/'trace-report.json',fidelity=prof['fidelity'],epsilon=prof['epsilon'],overlap=prof['overlap'],merge_colors=prof['merge_distance'])
        with contextlib.redirect_stdout(io.StringIO()):
            trace(args)
            compare(argparse.Namespace(reference=a.reference,svg=svg,plan=a.plan,output=folder,roi=[]))
        report=json.loads((folder/'comparison.json').read_text(encoding='utf-8'))
        failures=candidate_failures(report,a.max_mae,a.max_alpha_mae,a.min_edge_recall)
        size=svg.stat().st_size
        if a.max_bytes and size>a.max_bytes:failures.append('file size exceeds budget')
        report['candidate_id']=identity
        save_json(folder/'comparison.json',report)
        review_path=folder/'review-template.json'
        review=json.loads(review_path.read_text(encoding='utf-8'))
        review.update(candidate_id=identity,selection_reason='')
        save_json(review_path,review)
        items.append({'id':identity,'svg':str(svg.resolve()),'svg_sha256':report['svg_sha256'],'svg_bytes':size,'parameters':prof,'global':report['global'],'screen_pass':not failures,'screen_failures':failures,'comparison':str((folder/'comparison.json').resolve()),'review_template':str(review_path.resolve())})
        views.append(white(np.array(Image.open(folder/'render.png').convert('RGBA'))))
        titles.append(f'{identity}: {size:,} bytes')
    panel(views,titles,400).save(out/'candidates.png')
    for roi in rois:
        x,y,w,h=roi['box']
        panel([v[y:y+h,x:x+w] for v in views],titles,320,True).save(out/(roi['id']+'-candidates.png'))
    eligible=[item for item in items if item['screen_pass']]
    proposal=min(eligible,key=lambda item:item['svg_bytes'])['id'] if eligible else None
    save_json(out/'candidate-report.json',{'source_sha256':sha(a.reference),'plan_sha256':sha(a.plan),'toolkit_version':VERSION,'thresholds':{'max_mae':a.max_mae,'max_alpha_mae':a.max_alpha_mae,'min_edge_recall':a.min_edge_recall,'max_bytes':a.max_bytes},'candidates':items,'proposed_candidate':proposal,'quality_pass':None,'note':'A numerical proposal is not visual acceptance. Inspect full panels and critical crops, record candidate-specific observations and selection_reason, then audit the chosen review. If none passes, repair the plan or report the unmet budget.'})
    print(json.dumps({'candidate_report':str((out/'candidate-report.json').resolve()),'proposed_candidate':proposal,'visual_review':'pending'}))

def audit(a):
    review=json.loads(Path(a.review).read_text(encoding='utf-8-sig'));report=json.loads(Path(a.comparison).read_text(encoding='utf-8-sig'))
    errors=[]
    if review.get('svg_sha256')!=report['svg_sha256']:errors.append('Review refers to an older SVG')
    if a.svg and sha(a.svg)!=report['svg_sha256']:errors.append('SVG changed since comparison')
    if review.get('image_access')!='confirmed':errors.append('Actual image access unconfirmed')
    if not review.get('inspected_images'):errors.append('No inspected image paths recorded')
    if report.get('candidate_id'):
        if review.get('candidate_id')!=report['candidate_id']:errors.append('Review refers to a different candidate')
        if not review.get('selection_reason','').strip():errors.append('Candidate selection reason is missing')
    checks={c['id']:c for c in review.get('checks',[])}
    required=['whole-composition']+[r['id'] for r in report['crops'] if r['critical']]
    for rid in required:
        c=checks.get(rid,{})
        if c.get('status')!='pass' or not c.get('observation','').strip():errors.append('Unresolved critical visual check: '+rid)
    print(json.dumps({'review_complete':not errors,'errors':errors,'note':'This checks recorded evidence, not whether a model truly saw or understood the images.'}))
    if errors:raise SystemExit(2)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='img2svg '+VERSION)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('inspect');s.add_argument('reference');s.add_argument('--output',required=True);s.add_argument('--tile-size',type=int,default=768);s.add_argument('--roi',action='append',default=[])
    s=sub.add_parser('plan');s.add_argument('reference');s.add_argument('--work',required=True);s.add_argument('--plan',required=True);s.add_argument('--output',required=True);s.add_argument('--roi',action='append',default=[])
    s=sub.add_parser('compare');s.add_argument('reference');s.add_argument('--svg',required=True);s.add_argument('--plan');s.add_argument('--output',required=True);s.add_argument('--roi',action='append',default=[])
    s=sub.add_parser('audit');s.add_argument('--review',required=True);s.add_argument('--comparison',required=True);s.add_argument('--svg')
    s=sub.add_parser('candidates');s.add_argument('reference');s.add_argument('--work',required=True);s.add_argument('--plan',required=True);s.add_argument('--output',required=True)
    s.add_argument('--fidelities',default='faithful,balanced,compact');s.add_argument('--max-bytes',type=int,default=0);s.add_argument('--max-mae',type=float,default=4);s.add_argument('--max-alpha-mae',type=float,default=1);s.add_argument('--min-edge-recall',type=float,default=.97)
    a=p.parse_args();{'inspect':inspect,'plan':plan_review,'compare':compare,'audit':audit,'candidates':candidates}[a.command](a)
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
