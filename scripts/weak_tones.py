"""Conservative, source-grounded local tone correction for agent-free plans.

An image-wide k-means pigment can be too dark for one small, low-contrast
component. Correct only that component's paint, not the pigment everywhere.
Do not recolour ink, strong boundaries, very thin details or broad flat fills.
"""

import cv2
import numpy as np


def gradient_for_component(mask, source, fallback):
    """Fit an elliptical soft-tone model to one weak component.

    The principal axes model local light falloff. Native gradient paints are
    deliberately not emitted: vector_gradient_rings renders literal colours
    for robust independent rasterization instead.
    """
    ys,xs=np.nonzero(mask)
    if len(xs)<100:return None
    coords=np.column_stack((xs,ys)).astype(np.float64)
    center=coords.mean(axis=0)
    # PCA follows oblique soft shading without changing the hard ink geometry.
    covariance=np.cov(coords,rowvar=False)
    eigenvalues,axes=np.linalg.eigh(covariance)
    order=np.argsort(eigenvalues)[::-1]
    primary=axes[:,order[0]]
    angle=np.degrees(np.arctan2(primary[1],primary[0]))
    rotated=(coords-center)@axes[:,order]
    radii=np.maximum(np.percentile(np.abs(rotated),96,axis=0),3.)
    # Keep the transition fully inside the contour: the outer gradient stop
    # matches adjacent material instead of ending in a visible solid patch.
    radii*=1.12
    interior=cv2.erode(mask.astype(np.uint8),np.ones((5,5),np.uint8))>0
    if interior.sum()<60:return None
    inner_rgb=np.median(source[interior],axis=0)
    outer_ring=(cv2.dilate(mask.astype(np.uint8),np.ones((9,9),np.uint8))>0)&~mask.astype(bool)
    if outer_ring.sum()<24:return None
    neighbours=source[outer_ring].astype(float)
    close=np.linalg.norm(neighbours-inner_rgb,axis=1)<22
    if close.mean()<.65:return None
    outer_rgb=np.median(neighbours[close],axis=0)
    # Avoid introducing a false dark/light halo from an over-strong fit.
    if np.linalg.norm(outer_rgb-inner_rgb)>17:return None
    center_rgb=np.clip(np.rint(inner_rgb),0,255).astype(np.uint8)
    edge_rgb=np.clip(np.rint(outer_rgb),0,255).astype(np.uint8)
    return {'cx':float(center[0]),'cy':float(center[1]),'rx':float(radii[0]),
            'ry':float(radii[1]),'angle':float(angle),
            'center':center_rgb,'edge':edge_rgb}


def vector_gradient_rings(mask, fit, max_steps=16):
    """Approximate a soft radial gradient using portable literal-colour paths.

    Some deployed SVG rasterizers paint native SVG gradients black. Nested
    low-contrast paths are deterministic in PyMuPDF and browsers, and never
    extend beyond the approved mask or intrude into strong object edges.
    Returns cropped masks and their (x,y) translation for inexpensive tracing.
    """
    ys,xs=np.nonzero(mask)
    if not len(xs):return []
    x0=int(xs.min());y0=int(ys.min());x1=int(xs.max())+1;y1=int(ys.max())+1
    local=(mask[y0:y1,x0:x1]>0)
    yy,xx=np.indices(local.shape,dtype=np.float32)
    dx=xx+x0-fit['cx'];dy=yy+y0-fit['cy']
    angle=np.deg2rad(fit['angle']);co=np.cos(angle);si=np.sin(angle)
    u=dx*co+dy*si;v=-dx*si+dy*co
    distance=np.sqrt((u/fit['rx'])**2+(v/fit['ry'])**2)
    center=fit['center'].astype(float);outer=fit['edge'].astype(float)
    steps=min(max_steps,max(2,int(np.ceil(np.max(np.abs(center-outer))))))
    result=[(local.astype(np.uint8)*255,fit['edge'],x0,y0)]
    last=tuple(fit['edge'])
    # A soft tonal spot typically has a broad, nearly flat interior and only
    # fades into the surrounding material near its perimeter.  A uniform
    # centre-to-edge ramp would wash out the entire component.
    for k in range(steps-1,-1,-1):
        t=k/steps
        pigment=np.rint((1-t)*center+t*outer).astype(np.uint8)
        current=tuple(int(v) for v in pigment)
        if current==last:continue
        sub=local&(distance<=.55+.45*(k+.5)/steps)
        if not sub.any():continue
        result.append((sub.astype(np.uint8)*255,pigment,x0,y0))
        last=current
    return result


def separate_weak_tones(mask, rgb, paint, max_area, min_area=160, max_parts=24):
    """Return (remaining mask, [(component mask, local colour)], affected pixels).

    The caller owns the original drawing order. All masks are 0/255 uint8.
    RGB must be EXIF/ICC-normalized source pixels at the prepared resolution.
    """
    mask=np.asarray(mask,dtype=np.uint8)
    base=np.asarray(paint,dtype=np.float64)
    if min(base)<185 or max(base)<220 or not mask.any():return mask,[],0
    count,components,stats,_=cv2.connectedComponentsWithStats(mask,8)
    eligible=[i for i in range(1,count)
              if min_area<=int(stats[i,cv2.CC_STAT_AREA])<=max_area
              and min(stats[i,cv2.CC_STAT_WIDTH],stats[i,cv2.CC_STAT_HEIGHT])>=6]
    # Bound extra SVG paths and component-level calculations on noisy inputs.
    eligible.sort(key=lambda i:(-int(stats[i,cv2.CC_STAT_AREA]),i))
    remaining=mask.copy();out=[];changed=0
    for i in eligible[:max_parts]:
        x,y,w,h,_=map(int,stats[i]);pad=4
        x0=max(0,x-pad);y0=max(0,y-pad)
        x1=min(mask.shape[1],x+w+pad);y1=min(mask.shape[0],y+h+pad)
        local=components[y0:y1,x0:x1]==i
        image=rgb[y0:y1,x0:x1].astype(np.float32)
        inner=cv2.erode(local.astype(np.uint8),np.ones((3,3),np.uint8))>0
        if inner.sum()<min_area//2:continue
        original=np.median(image[inner],axis=0)
        # Ignore hard edge shapes and material boundaries; a weak shade is
        # surrounded by similar original colours, not an ink or object edge.
        ring=(cv2.dilate(local.astype(np.uint8),np.ones((7,7),np.uint8))>0)&~local
        neighbour=image[ring]
        if len(neighbour)<24:continue
        distances=np.linalg.norm(neighbour-original,axis=1)
        nearby=neighbour[distances<=22]
        if len(nearby)<max(24,int(len(neighbour)*.65)):continue
        if np.linalg.norm(np.median(nearby,axis=0)-original)>12:continue
        # Relax the neighbour-colour gap for continuous illumination, but not
        # for a genuinely sharp material boundary of similar hue.
        if np.linalg.norm(np.median(nearby,axis=0)-original)>6:
            luminance=cv2.cvtColor(image.astype(np.uint8),cv2.COLOR_RGB2GRAY).astype(np.float32)
            gx=cv2.Sobel(luminance,cv2.CV_32F,1,0,ksize=3)/8
            gy=cv2.Sobel(luminance,cv2.CV_32F,0,1,ksize=3)/8
            edge=np.hypot(gx,gy)
            indices=np.flatnonzero(ring)
            flat_soft=np.zeros(ring.size,bool)
            flat_soft[indices[distances<=22]]=True
            if np.percentile(edge[flat_soft.reshape(ring.shape)],90)>2.2:continue
        corrected=np.clip(np.rint(original),0,255).astype(np.uint8)
        shift=float(np.linalg.norm(base-corrected.astype(float)))
        local_transition=float(np.linalg.norm(np.median(nearby,axis=0)-original))
        # A pigment can have the correct mean while its quantized contour
        # fabricates an edge that was soft in the source. Treat both cases.
        if shift>18 or (shift<3 and local_transition<3):continue
        component=np.zeros_like(mask)
        component[y0:y1,x0:x1][local]=255
        remaining[y0:y1,x0:x1][local]=0
        out.append((component,corrected))
        changed+=int(stats[i,cv2.CC_STAT_AREA])
    return remaining,out,changed
