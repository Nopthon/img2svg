"""Normalize a bounded, presentation-attribute SVG to a portable static SVG.

No third-party dependencies. Not a general browser CSS engine. Unsupported
selectors, symbols and external references fail instead of silently changing art.
"""
import argparse, copy, json, re, math
from pathlib import Path
import xml.etree.ElementTree as ET
from version import VERSION

NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
INHERITED={'fill','stroke','color','fill-rule','clip-rule','stroke-width','stroke-linejoin','stroke-linecap','stroke-miterlimit','stroke-dasharray','stroke-dashoffset','fill-opacity','stroke-opacity','visibility'}
SHAPES={'path','rect','circle','ellipse','polygon','polyline','line'}
RESOURCES={'linearGradient','radialGradient'}
UNSUPPORTED_RESOURCES={'clipPath','mask','filter','pattern','symbol'}
ELEMENTS=SHAPES|RESOURCES|{'svg','g','defs','title','desc','metadata','stop'}
ATTRIBUTES=INHERITED|{
    'id','version','viewBox','preserveAspectRatio','width','height','x','y',
    'x1','y1','x2','y2','cx','cy','r','rx','ry','fx','fy','fr','d','points',
    'transform','opacity','display','pathLength','offset','stop-color',
    'stop-opacity','gradientUnits','gradientTransform','spreadMethod','href',
    'vector-effect','shape-rendering','color-interpolation','color-rendering',
    'overflow','role','focusable',
}

def tag(e):return e.tag.rsplit('}',1)[-1]
def load_svg(path):
    text=Path(path).read_text(encoding='utf-8-sig')
    if re.search(r'<!DOCTYPE|<!ENTITY',text,re.I):raise ValueError('DTD/entities are not supported')
    root=ET.fromstring(text)
    if tag(root)!='svg':raise ValueError('Expected SVG root')
    return root

def literal(value, variables):
    for _ in range(12):
        m=re.fullmatch(r'var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)',value.strip())
        if not m:return value.strip()
        value=variables.get(m[1],m[2])
        if value is None:raise ValueError('CSS variable has no resolvable value/fallback')
    raise ValueError('Cyclic CSS variable')

def normalize(root):
    root=copy.deepcopy(root)
    for e in root.iter():
        if tag(e)=='style' and (e.text or '').strip():raise ValueError('Resolve stylesheet selectors before normalization; inline presentation attributes required')
        if tag(e) in {'image','foreignObject','script','animate','animateTransform','set'}:raise ValueError('Raster, foreign content, or animation is not a portable static SVG')
    lookup={e.get('id'):e for e in root.iter() if e.get('id')}
    serial=[0]

    def visit(e, inherited, variables, chain=()):
        local_vars=dict(variables); own=dict(e.attrib)
        for rule in own.pop('style','').split(';'):
            if not rule.strip():continue
            key,sep,value=rule.partition(':')
            if not sep:raise ValueError('Malformed inline style')
            key=key.strip();value=value.strip()
            if key.startswith('--'):local_vars[key]=value
            elif key in INHERITED|{'opacity','stop-color','stop-opacity','display'}:own[key]=value
            else:raise ValueError('Unsupported inline CSS: '+key)
        attrs={k:literal(v,local_vars) for k,v in own.items() if not k.startswith('--')}
        if attrs.get('display')=='none':return None
        state=dict(inherited)
        for k in INHERITED:
            if k in attrs:
                if attrs[k]=='inherit':attrs[k]=state.get(k,'none' if k=='stroke' else '#000000')
                state[k]=attrs[k]
        if tag(e)=='use':
            ref=attrs.pop('href',attrs.pop('{http://www.w3.org/1999/xlink}href',''))
            if not ref.startswith('#') or ref[1:] not in lookup:raise ValueError('Missing/external use reference: '+ref)
            if ref in chain:raise ValueError('Cyclic use reference')
            target=lookup[ref[1:]]
            if tag(target) in {'symbol','svg'}:raise ValueError('Symbol/nested viewport use must be resolved separately')
            x=attrs.pop('x','0');y=attrs.pop('y','0')
            if x!='0' or y!='0':attrs['transform']=(attrs.get('transform','')+f' translate({x} {y})').strip()
            attrs.pop('width',None);attrs.pop('height',None)
            result=ET.Element('{'+NS+'}g',attrs)
            clone=copy.deepcopy(target);serial[0]+=1;prefix=f'instance-{serial[0]}-'
            rename={n.get('id'):prefix+n.get('id') for n in clone.iter() if n.get('id')}
            for n in clone.iter():
                if n.get('id'):n.set('id',rename[n.get('id')])
                for key,val in list(n.attrib.items()):
                    if val.startswith('#') and val[1:] in rename and key.endswith('href'):n.set(key,'#'+rename[val[1:]])
                    n.set(key,re.sub(r'url\(#([^)]*)\)',lambda m:'url(#'+rename.get(m[1],m[1])+')',n.get(key)))
            child=visit(clone,state,local_vars,chain+(ref,))
            if child is not None:result.append(child)
            return result
        result=ET.Element(e.tag,attrs);result.text=e.text;result.tail=e.tail
        if tag(e)=='stop':
            v=result.get('stop-color','#000000')
            if re.fullmatch(r'#[0-9a-fA-F]{3}',v):v='#'+''.join(c*2 for c in v[1:])
            result.set('stop-color',v)
        if tag(e) in SHAPES:
            for k,v in state.items():result.set(k,v)
            for key in ['fill','stroke']:
                val=result.get(key,'none' if key=='stroke' else '#000000')
                if val=='currentColor':val=state.get('color','#000000')
                named={'black':'#000000','white':'#ffffff','red':'#ff0000','blue':'#0000ff','green':'#008000'}
                val=named.get(val.lower(),val)
                if re.fullmatch(r'#[0-9a-fA-F]{3}',val):val='#'+''.join(c*2 for c in val[1:])
                if not (re.fullmatch(r'#[0-9a-fA-F]{6}',val) or val=='none' or re.fullmatch(r'url\(#[\w.-]+\)',val)):
                    raise ValueError('Convert paint to #RRGGBB + fill/stroke-opacity: '+val)
                result.set(key,val.lower() if val.startswith('#') else val)
        for child in e:
            if tag(e)=='defs' and tag(child) not in RESOURCES:
                if tag(child) in UNSUPPORTED_RESOURCES:raise ValueError('Unsupported resource in <defs>: '+tag(child))
                continue
            rendered=visit(child,state,local_vars,chain)
            if rendered is not None:result.append(rendered)
        return result
    out=visit(root,{'fill':'#000000','stroke':'none'},{})
    out.set('version','1.1');out.set('preserveAspectRatio','xMidYMid meet')
    validate(out)
    return out

def validate(root):
    if root.tag!='{'+NS+'}svg':raise ValueError('Expected SVG namespace and root')
    ids=[];paints=set();paths=0
    for e in root.iter():
        kind=tag(e)
        if e.tag!='{'+NS+'}'+kind or kind not in ELEMENTS:
            raise ValueError('Outside this portable SVG profile: '+kind)
        if e.get('id'):ids.append(e.get('id'))
        for key,val in e.attrib.items():
            local=key.rsplit('}',1)[-1]
            if local.lower().startswith('on'):raise ValueError('SVG event attributes are not static: '+key)
            if key.startswith('{'):
                if key not in {'{http://www.w3.org/1999/xlink}href','{http://www.w3.org/XML/1998/namespace}space','{http://www.w3.org/XML/1998/namespace}lang'}:
                    raise ValueError('Unsupported attribute namespace: '+key)
            elif key not in ATTRIBUTES and not re.fullmatch(r'(data|aria)-[a-z][a-z0-9-]*',key):
                raise ValueError('Unsupported SVG attribute: '+key)
            if local=='href' and kind not in RESOURCES:raise ValueError('Only gradients may reference other gradients')
            if key in {'opacity','fill-opacity','stroke-opacity','stop-opacity'}:
                number=float(val)
                if not math.isfinite(number) or not 0<=number<=1:raise ValueError('Opacity must be finite and within 0..1')
            if key=='style':raise ValueError('Inline CSS must be resolved to presentation attributes')
            if 'var(' in val or val=='currentColor' or 'base64' in val.lower():raise ValueError('Nonliteral SVG dependency: '+key)
            if key.endswith('href') and not val.startswith('#'):raise ValueError('External reference')
            for u in re.findall(r'url\((.*?)\)',val):
                if not u.strip().strip('\"\'').startswith('#'):raise ValueError('External paint URL')
        if kind=='stop' and not re.fullmatch(r'#[0-9a-fA-F]{6}',e.get('stop-color','')):raise ValueError('Gradient stops need literal #RRGGBB')
        if kind in SHAPES:
            paths+=1
            for key in ('fill','stroke'):
                val=e.get(key)
                if val is None:raise ValueError('Shape lacks explicit '+key)
                if not (val=='none' or re.fullmatch(r'#[0-9a-fA-F]{6}',val) or re.fullmatch(r'url\(#[\w.-]+\)',val)):
                    raise ValueError('Unsupported paint: '+val)
                if val.startswith('#'):paints.add(val)
    if len(set(ids))!=len(ids):raise ValueError('Duplicate SVG IDs')
    lookup={e.get('id'):e for e in root.iter() if e.get('id')}
    gradient_links={}
    for e in root.iter():
        for key,v in e.attrib.items():
            for ref in re.findall(r'url\(#([^)]*)\)',v):
                if ref not in lookup or tag(lookup[ref]) not in RESOURCES:raise ValueError('Expected local gradient reference '+ref)
            if key.endswith('href'):
                ref=v[1:]
                if ref not in lookup or tag(lookup[ref]) not in RESOURCES:raise ValueError('Expected local gradient reference '+ref)
                gradient_links[id(e)]=id(lookup[ref])
    for start in gradient_links:
        seen=set();current=start
        while current in gradient_links:
            if current in seen:raise ValueError('Cyclic gradient reference')
            seen.add(current);current=gradient_links[current]
    dims=[float(v) for v in re.split(r'[\s,]+',root.get('viewBox','').strip()) if v]
    if len(dims)!=4 or not all(map(math.isfinite,dims)) or dims[2]<=0 or dims[3]<=0:raise ValueError('Finite positive viewBox required')
    return {'native_shapes':paths,'literal_colors':len(paints),'unique_ids':len(ids),'viewBox':dims}

def write_svg(root,path):
    validate(root)
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version='img2svg '+VERSION)
    p.add_argument('input');p.add_argument('--output');p.add_argument('--check',action='store_true')
    a=p.parse_args();root=load_svg(a.input)
    if not a.check:
        if not a.output:p.error('--output required unless --check')
        root=normalize(root);write_svg(root,a.output)
    print(json.dumps(validate(root),ensure_ascii=False))
if __name__=='__main__':main()
