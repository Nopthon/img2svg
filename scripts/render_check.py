"""Render with independent MuPDF; optionally measure against a reference image."""
import argparse,json
from pathlib import Path
from version import VERSION

def main():
    try:
        import pymupdf as fitz
    except ImportError:
        raise SystemExit('pymupdf is not installed; run pip install -r requirements-render.txt for independent rendering')
    import numpy as np
    from PIL import Image,ImageOps
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='img2svg '+VERSION)
    p.add_argument('svg');p.add_argument('--png',required=True);p.add_argument('--reference');p.add_argument('--width',type=int);p.add_argument('--report')
    a=p.parse_args()
    document=fitz.open(a.svg);page=document[0]
    scale=(a.width/page.rect.width) if a.width else 1
    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=True)
    Path(a.png).parent.mkdir(parents=True,exist_ok=True);pix.save(a.png)
    output=Image.open(a.png).convert('RGBA');white=Image.new('RGBA',output.size,'white');white.alpha_composite(output)
    rgb=np.asarray(white.convert('RGB')).astype(np.float32)
    chroma=rgb.max(axis=2)-rgb.min(axis=2)
    report={'renderer':'MuPDF '+fitz.VersionBind,'size':list(output.size),'colored_pixel_fraction':float((chroma>15).mean())}
    if a.reference:
        ref=ImageOps.exif_transpose(Image.open(a.reference)).convert('RGBA')
        if ref.size!=output.size:ref=ref.resize(output.size,Image.Resampling.LANCZOS)
        bg=Image.new('RGBA',ref.size,'white');bg.alpha_composite(ref)
        delta=rgb-np.asarray(bg.convert('RGB')).astype(np.float32)
        report.update(rgb_mae=float(np.abs(delta).mean()),rgb_rmse=float(np.sqrt((delta**2).mean())))
    if a.report:Path(a.report).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
if __name__=='__main__':main()
