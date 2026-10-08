"""Single fidelity <-> size control shared by every stage.

0 = smallest file (aggressively merged, coarse contours);
100 = most faithful (per-contour pixel tracing).

Both the command-line tool (`--fidelity`) and the agent skill use this one axis.
The skill asks the user where to sit on it. Accepts a number 0..100 or one of
the named presets `faithful` (100), `balanced` (55), `compact` (0).
"""
NAMES={'faithful':100,'balanced':55,'compact':0}

def resolve(value):
    if value is None:return None
    if isinstance(value,str):
        v=value.strip().lower()
        if v in NAMES:return float(NAMES[v])
        try:value=float(v)
        except ValueError:raise ValueError('fidelity must be 0..100 or one of: '+', '.join(NAMES))
    value=float(value)
    if not 0<=value<=100:raise ValueError('fidelity must be within 0..100')
    return value

def profile(fidelity):
    """Map a fidelity value to concrete stage parameters, interpolated linearly."""
    f=resolve(fidelity)
    if f is None:f=100.0
    t=f/100.0
    return {
        'fidelity':f,
        'colors':int(round(32+48*t)),
        'label_min_area':int(round(16*(1-t))),
        'epsilon':round(1.5-0.95*t,3),
        'overlap':round(1.4+0.2*(1-t),3),
        'merge_distance':int(round(24*(1-t))),
    }
