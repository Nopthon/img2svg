"""End-to-end regression checks: colors, holes, alpha, thin strokes and rejection.
Run with --work <scratch-directory>; requires generation + rendering packages.
"""
import argparse,json,subprocess,sys
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image,ImageDraw
import pymupdf
from svg_compat import normalize,load_svg,write_svg,validate
from version import VERSION

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='img2svg '+VERSION)
    p.add_argument('--work',required=True);a=p.parse_args()
    work=Path(a.work).resolve();work.mkdir(parents=True,exist_ok=True);scripts=Path(__file__).resolve().parent
    def run(*args):subprocess.run([sys.executable,*map(str,args)],check=True,capture_output=True,text=True,encoding='utf-8',errors='replace')
    im=Image.new('RGBA',(128,96),(0,0,0,0));draw=ImageDraw.Draw(im)
    draw.rectangle((8,8,119,87),fill='#fff7e5')
    draw.ellipse((20,17,77,75),fill='#38ab73')
    draw.ellipse((36,33,60,58),fill='#fff7e5')
    draw.rectangle((91,24,108,59),fill=(195,73,122,128))
    draw.line((16,81,100,81),fill='#34383c',width=1)
    source=work/'reference.png';im.save(source)
    run(scripts/'vectorize.py','prepare',source,'--work',work/'analysis','--colors',6,'--denoise',0)
    palette=json.loads((work/'analysis/palette.json').read_text(encoding='utf-8'))['colors']
    nearest=lambda target:min(palette,key=lambda e:sum((a-b)**2 for a,b in zip(e['rgb'],target)))['index']
    ink=nearest((52,56,60));green=nearest((56,171,115));rose=nearest((195,73,122))
    plan={'coordinate_size':[128,96],'default':{'id':'paper','base':'#fff7e5','phase':'background'},'roles':{'ink':[ink]},'regions':[{'id':'green-ring','base':'#38ab73','polygon':[[0,0],[128,0],[128,96],[0,96]],'include_colors':[green,ink],'roles':{'ink':[ink]}},{'id':'rose-window','base':'#c3497a','polygon':[[85,20],[116,20],[116,64],[85,64]],'include_colors':[rose],'phase':'shadow'}]}
    (work/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
    result=work/'illustration.svg'
    run(scripts/'vectorize.py','trace','--work',work/'analysis','--plan',work/'plan.json','--output',result,'--line-art',work/'lines.svg','--epsilon',.15,'--overlap',.65)
    validate(load_svg(result))
    doc=pymupdf.open(result);pix=doc[0].get_pixmap(alpha=True);pix.save(work/'render.png')
    rgba=np.asarray(Image.open(work/'render.png').convert('RGBA'))
    assert rgba.shape==(96,128,4),'Original dimensions changed'
    assert int(rgba[2,2,3])==0,'Transparent background lost'
    assert 110<=int(rgba[40,100,3])<=145,'Semitransparent paint alpha changed'
    assert int(rgba[47,48,0])>240 and int(rgba[47,48,1])>225,'Contour hole filled'
    assert int(rgba[45,27,1])>int(rgba[45,27,0])+60,'Green paint missing'
    assert int((rgba[80:83,16:101,:3].min(axis=0).max(axis=1)<150).sum())>=70,'One-pixel line lost'
    run(scripts/'make_demo.py',result,'--output',work/'index.html','--line-art',work/'lines.svg','--plan',work/'plan.json')
    page=(work/'index.html').read_text(encoding='utf-8')
    assert 'var(' not in page and '<image' not in page and '<canvas' not in page
    assert '>Highlight</button>' not in page and '>Sketch</button>' not in page,'Empty stages retained'
    assert '>Shadow</button>' in page and '>Line art</button>' in page,'Existing stages removed'
    # Old-style fallback paint and reusable geometry must become visible literal geometry.
    old=work/'legacy.svg';old.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs><g id="mark"><rect width="20" height="20" fill="var(--paint,#38ab73)"/></g></defs><use href="#mark"/></svg>',encoding='utf-8')
    fixed=normalize(load_svg(old));write_svg(fixed,work/'fixed.svg')
    raw=ET.tostring(fixed,encoding='unicode');assert 'var(' not in raw and '<use' not in raw
    pix=pymupdf.open(work/'fixed.svg')[0].get_pixmap();pixel=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)[10,10,:3]
    assert pixel[1]>pixel[0]+60,'Compatibility repair lost paint'
    unsupported=ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><style>rect{fill:red}</style><rect width="1" height="1"/></svg>')
    try:normalize(unsupported)
    except ValueError:pass
    else:raise AssertionError('Unsupported stylesheet was silently ignored')
    print(json.dumps({'passed':['dimensions','transparent_background','partial_alpha','hole','literal_color','one_pixel_line','demo_generation','legacy_color_repair','unsupported_css_rejection'],'work':str(work)}))
if __name__=='__main__':main()
