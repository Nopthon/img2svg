"""Opt-in, region-local merging of small low-contrast pigment islands.
Never deletes to transparency; never changes alpha or semantic ownership.
"""
import cv2
import numpy as np

def clean_regions(labels,palette,alpha,mapping,regions,global_roles):
    from vectorize import role_for
    result=labels.copy();reports=[]
    for ri,region in enumerate(regions):
        cfg=region.get('cleanup',{})
        if not cfg.get('enabled',False):continue
        area=int(cfg.get('max_area',3));delta=float(cfg.get('max_rgb_distance',12));aspect=float(cfg.get('max_aspect',2))
        if not 1<=area<=64 or not 0<=delta<=60 or not 1<=aspect<=4:raise ValueError('Cleanup bounds: area 1..64, RGB distance 0..60, aspect 1..4')
        protected=set(cfg.get('protect_roles',['ink','detail','highlight']))
        owned=(mapping==ri)&(alpha==255);changed=0;merged=0;errors=[]
        # Snapshot decisions: candidates cannot trigger cascading merges.
        for ci in np.unique(labels[owned]):
            role=role_for(region,int(ci),global_roles)
            if role in protected:continue
            mask=np.uint8(owned&(labels==ci));count,cc,stats,_=cv2.connectedComponentsWithStats(mask,8)
            for index in range(1,count):
                x,y,w,h,n=map(int,stats[index])
                if n>area or max(w,h)/min(w,h)>aspect:continue
                x0=max(0,x-1);y0=max(0,y-1);x1=min(labels.shape[1],x+w+1);y1=min(labels.shape[0],y+h+1)
                component=cc[y0:y1,x0:x1]==index
                ring=(cv2.dilate(component.astype('uint8'),np.ones((3,3),np.uint8))>0)&~component
                eligible=ring&owned[y0:y1,x0:x1]
                # Avoid crossing object/alpha boundaries, including a semitransparent rim.
                if not eligible.any() or np.any(ring&~owned[y0:y1,x0:x1]):continue
                candidates,counts=np.unique(labels[y0:y1,x0:x1][eligible],return_counts=True)
                choices=[]
                for cj,number in zip(candidates,counts):
                    if cj==ci or role_for(region,int(cj),global_roles)!=role:continue
                    distance=float(np.linalg.norm(palette[int(ci)].astype(float)-palette[int(cj)]))
                    if distance<=delta and number>=max(2,n):choices.append((distance,-int(number),int(cj)))
                if not choices:continue
                distance,_,target=min(choices)
                result[y0:y1,x0:x1][component]=target;changed+=n;merged+=1;errors.append(distance)
        reports.append({'region':region['id'],'merged_components':merged,'changed_pixels':changed,'max_rgb_distance':max(errors,default=0),'settings':cfg})
    return result,reports
