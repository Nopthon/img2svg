"""Independent rendering using the same colour and alpha rules as visual review."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image
from vectorize import image_rgba,save_json
from visual_review import render_svg,white,metrics
from version import VERSION


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='img2svg '+VERSION)
    p.add_argument('svg');p.add_argument('--png',required=True)
    p.add_argument('--reference');p.add_argument('--width',type=int)
    p.add_argument('--report')
    p.add_argument('--quantized-preview',help='RGBA preview produced by prepare; compare rendered SVG against the prepared palette, separately from the original image')
    a=p.parse_args()
    actual,_,renderer=render_svg(a.svg,a.width)
    rgb=white(actual).astype(float)
    report={'renderer':renderer,'toolkit_version':VERSION,'size':[actual.shape[1],actual.shape[0]],'colored_pixel_fraction':float(((rgb.max(axis=2)-rgb.min(axis=2))>15).mean())}
    if a.quantized_preview:
        prepared=image_rgba(a.quantized_preview)
        if prepared.shape!=actual.shape:
            raise ValueError('Quantized preview dimensions differ from SVG render')
        difference=rgb-white(prepared).astype(float)
        report['rendered_vs_prepared_rgb_bias']={channel:float(value) for channel,value in zip('rgb',difference.mean(axis=(0,1)))}
        report['rendered_vs_prepared_rgb_mae']=float(np.abs(difference).mean())
    if a.reference:
        ref=image_rgba(a.reference)
        h,w=actual.shape[:2];rh,rw=ref.shape[:2]
        if abs(rw/rh-w/h)>max(1/rh,1/h):raise ValueError('Reference aspect ratio differs from SVG')
        if ref.shape!=actual.shape:
            if a.width is None:raise ValueError('Reference dimensions differ; use --width only for intentional scaled comparison')
            ref=np.array(Image.fromarray(ref).resize((w,h),Image.Resampling.LANCZOS))
        report.update(metrics(ref,actual))
        # Preserve report fields consumed by existing callers.
        delta=rgb-white(ref).astype(float)
        report.update(rgb_mae=float(np.abs(delta).mean()),rgb_rmse=float(np.sqrt((delta**2).mean())))
    Path(a.png).parent.mkdir(parents=True,exist_ok=True)
    Image.fromarray(actual).save(a.png)
    if a.report:
        Path(a.report).parent.mkdir(parents=True,exist_ok=True)
        save_json(a.report,report)
    print(json.dumps(report))

if __name__=='__main__':main()
