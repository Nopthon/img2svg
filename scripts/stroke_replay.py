"""Continuous replay centerlines; does not replace the faithful final ink geometry."""
import cv2
import numpy as np
from vectorize import skeletonize,node,write_svg

def chains(mask,mapping,max_half_width):
    h,w=mask.shape
    distance=cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,3)
    sk=skeletonize(mask);sk[distance>max_half_width]=0
    nodes={int(y)*w+int(x) for y,x in np.argwhere(sk)};neighbors={}
    for p in sorted(nodes):
        x,y=p%w,p//w;near=[]
        for dx,dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
            q=p+dy*w+dx
            if not (0<=x+dx<w and 0<=y+dy<h) or q not in nodes:continue
            if mapping[y,x]!=mapping[y+dy,x+dx]:continue
            # Remove diagonal shortcuts across an existing orthogonal corner.
            if dx and dy and (p+dx in nodes or p+dy*w in nodes):continue
            near.append(q)
        neighbors[p]=near
    paired={}
    for p,near in neighbors.items():
        if len(near)==2:
            paired[p,near[0]]=near[1];paired[p,near[1]]=near[0]
        elif len(near)>2:
            options=[]
            for i,a in enumerate(near):
                va=np.array([a%w-p%w,a//w-p//w],float)
                for b in near[i+1:]:
                    vb=np.array([b%w-p%w,b//w-p//w],float)
                    score=float(np.dot(va,vb)/(np.linalg.norm(va)*np.linalg.norm(vb)))
                    if score<=-.70:options.append((score,a,b))
            used=set()
            for _,a,b in sorted(options):
                if a not in used and b not in used:paired[p,a]=b;paired[p,b]=a;used.update([a,b])
    visited=set();result=[]
    edges=[(p,q) for p in neighbors for q in neighbors[p]]
    edges.sort(key=lambda e:((e[0],e[1]) in paired,e))
    for start,nxt in edges:
        edge=tuple(sorted((start,nxt)))
        if edge in visited:continue
        seq=[start];prev=start;cur=nxt;visited.add(edge)
        while True:
            seq.append(cur);target=paired.get((cur,prev))
            if target is None or tuple(sorted((cur,target))) in visited:break
            visited.add(tuple(sorted((cur,target))));prev,cur=cur,target
        result.append(seq)
    return result,distance

def curve_path(points,support):
    def pair(p):return f'{p[0]:.3f} {p[1]:.3f}'
    d='M'+pair(points[0]);h,w=support.shape
    for i in range(len(points)-1):
        p0=points[max(0,i-1)];p1=points[i];p2=points[i+1];p3=points[min(len(points)-1,i+2)]
        c1=p1+(p2-p0)/6;c2=p2-(p3-p1)/6
        ts=np.linspace(0,1,max(6,int(np.linalg.norm(p2-p1)*2)+1))[:,None]
        samples=(1-ts)**3*p1+3*(1-ts)**2*ts*c1+3*(1-ts)*ts**2*c2+ts**3*p2
        xy=np.floor(samples).astype(int)
        valid=(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
        if valid.all() and support[xy[:,1],xy[:,0]].all():d+='C'+pair(c1)+' '+pair(c2)+' '+pair(p2)
        else:d+='L'+pair(p2)
    return d

def make_lines(mask,mapping,regions,w,h,path,settings=None):
    settings=settings or {};scale=max(.35,min(w,h)/1000)
    half=float(settings.get('max_half_width',max(2,4*scale)))
    minimum=float(settings.get('min_length',max(2,4*scale)))
    epsilon=float(settings.get('epsilon',.40*scale))
    if not 0<half<=50 or not 0<=minimum<=100 or not 0<=epsilon<=2:raise ValueError('Invalid replay width/length/epsilon')
    sequences,distance=chains(mask,mapping,half)
    support=cv2.dilate(mask.astype(np.uint8),np.ones((3,3),np.uint8))>0;lines=[]
    for seq in sequences:
        xy=np.array([[p%w+.5,p//w+.5] for p in seq],np.float32)
        length=float(np.linalg.norm(np.diff(xy,axis=0),axis=1).sum())
        if length<minimum:continue
        points=cv2.approxPolyDP(xy,epsilon,False).reshape(-1,2)
        if len(points)<2:continue
        owner=int(mapping[seq[len(seq)//2]//w,seq[len(seq)//2]%w])
        width=float(np.clip(np.median([distance[p//w,p%w] for p in seq])*1.8,.65,half*2))
        lines.append((regions[owner].get('ink_order',owner),int(xy[:,1].min()),int(xy[:,0].min()),curve_path(points,support),length,width))
    root=node('svg',{'viewBox':f'0 0 {w} {h}','width':w,'height':h,'version':'1.1'})
    for i,(_,__,___,d,length,width) in enumerate(sorted(lines)):
        root.append(node('path',{'id':f'pencil-connected-{i}','d':d,'fill':'none','stroke':'#71666a','stroke-width':f'{width:.3f}','stroke-linecap':'round','stroke-linejoin':'round'}))
    write_svg(root,path);return len(lines)
