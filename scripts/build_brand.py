"""Build the approved Entrelíneas identity as self-contained SVG paths.

The symbol is drawn with cubic Béziers. The approved custom lettering is
outlined from the approved concept; no fonts or bitmap images are embedded.
"""
from pathlib import Path
from PIL import Image, ImageFilter
from math import hypot

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'static/brand'
OUT.mkdir(exist_ok=True)
TEMPLATES = ROOT / 'templates/brand'
TEMPLATES.mkdir(exist_ok=True)
VIOLET = '#6845a5'
INK = '#16151e'
PAGE = 'M0 0C99 3 220 40 240 108V324C208 264 155 248 116 276C66 312 102 382 184 398V411C80 407 0 369 0 287Z'
SYMBOL = f'<path d="{PAGE}"/><path d="{PAGE}" transform="translate(512 0) scale(-1 1)"/>'

def simplify(points, epsilon=1.25):
    if len(points)<3:
        return points
    a,b=points[0],points[-1]
    dx,dy=b[0]-a[0],b[1]-a[1]
    length=hypot(dx,dy)
    distances=[abs(dy*(p[0]-a[0])-dx*(p[1]-a[1]))/length if length else hypot(p[0]-a[0],p[1]-a[1]) for p in points]
    index=max(range(len(points)),key=distances.__getitem__)
    if distances[index]>epsilon:
        return simplify(points[:index+1],epsilon)[:-1]+simplify(points[index:],epsilon)
    return [a,b]

def outline(mask):
    """Trace oriented pixel edges, retain counters, simplify subpixel noise."""
    pixels=mask.load()
    width,height=mask.size
    edges={}
    def occupied(x,y):
        return 0<=x<width and 0<=y<height and pixels[x,y]
    for y in range(height):
        for x in range(width):
            if not occupied(x,y):
                continue
            for outside,a,b in [((x,y-1),(x,y),(x+1,y)),((x+1,y),(x+1,y),(x+1,y+1)),((x,y+1),(x+1,y+1),(x,y+1)),((x-1,y),(x,y+1),(x,y))]:
                if not occupied(*outside):
                    edges.setdefault(a,[]).append(b)
    paths=[]
    while edges:
        start=next(iter(edges))
        current=start
        points=[start]
        while True:
            choices=edges[current]
            nxt=choices.pop()
            if not choices:
                del edges[current]
            points.append(nxt)
            current=nxt
            if current==start:
                break
        if len(points)<12:
            continue
        mid=len(points)//2
        points=simplify(points[:mid+1])[:-1]+simplify(points[mid:])[:-1]
        # Smooth raster stair steps by quadratic joins. Large corners retain
        # their shape to within the subpixel outline tolerance.
        n=len(points)
        midpoint=lambda a,b:((a[0]+b[0])/2,(a[1]+b[1])/2)
        begin=midpoint(points[-1],points[0])
        fmt=lambda p:f'{p[0]:g} {p[1]:g}'
        commands=['M'+fmt(begin)]
        for j,p in enumerate(points):
            before,after=points[j-1],points[(j+1)%n]
            u=(p[0]-before[0],p[1]-before[1])
            v=(after[0]-p[0],after[1]-p[1])
            cosine=(u[0]*v[0]+u[1]*v[1])/(hypot(*u)*hypot(*v))
            end=fmt(midpoint(p,after))
            commands.append(('L'+fmt(p)+' L'+end) if cosine<.45 else ('Q'+fmt(p)+' '+end))
        paths.append(' '.join(commands)+'Z')
    return ' '.join(paths)

source=Image.open(ROOT/'docs/brand-preview/entrelineas-v2/propuesta-05-combinada.png').convert('RGB').crop((145,650,1110,830))
dark=Image.new('1',source.size)
accent=Image.new('1',source.size)
for y in range(source.height):
    for x in range(source.width):
        r,g,b=source.getpixel((x,y))
        if max(r,g,b)<155 and b-r<35:
            dark.putpixel((x,y),1)
        elif b>g*1.3 and r>g*1.2 and g<145:
            accent.putpixel((x,y),1)
WORD=f'<path fill-rule="evenodd" d="{outline(dark.convert("L").filter(ImageFilter.MedianFilter(3)))}"/>'
# The distinctive í accent is redrawn as a single precise page-shaped Bézier.
ACCENT='<path d="M525 54C539 33 555 25 569 9V33C569 47 551 57 525 54Z"/>'

def groups(kind, mono=False):
    color='currentColor' if mono else VIOLET
    if kind=='symbol':
        return f'<g class="brand-accent" fill="{color}">{SYMBOL}</g>'
    word=f'<g class="brand-ink" fill="currentColor">{WORD}</g><g class="brand-accent" fill="{color}">{ACCENT}</g>'
    if kind=='wordmark':
        return word
    return f'<g transform="translate(0 14) scale(.37)" class="brand-accent" fill="{color}">{SYMBOL}</g><g transform="translate(225 0)">{word}</g>'

for kind,box in [('symbol','0 0 512 412'),('wordmark','0 0 965 180'),('logo','0 0 1190 180')]:
    for mono in (False,True):
        suffix='-mono' if mono else ''
        content=groups(kind,mono)
        # External SVG assets have their own adaptive theme. Inline templates
        # use the app's CSS variables and inherit the surrounding text color.
        style='' if mono else '<style>@media(prefers-color-scheme:dark){svg{color:#f0ebf8}.brand-accent{fill:#c3a9ff}}</style>'
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box}" color="{INK}"><title>Entrelíneas</title>{style}{content}</svg>\n'
        (OUT/f'entrelineas-{kind}{suffix}.svg').write_text(svg,encoding='utf-8')
        if mono:
            (OUT/f'entrelineas-{kind}-white.svg').write_text(svg.replace(f'color="{INK}"','color="#fff"'),encoding='utf-8')
    if kind in ('logo','wordmark'):
        (TEMPLATES/f'{kind}.html').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" class="brand-{kind}" viewBox="{box}" aria-hidden="true" focusable="false">{groups(kind)}</svg>\n',encoding='utf-8')

favicon=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="15" fill="{VIOLET}"/><g transform="translate(9 13.5) scale(.09)" fill="#fff">{SYMBOL}</g></svg>\n'
(ROOT/'static/favicon.svg').write_text(favicon,encoding='utf-8')
print('Six standalone SVG assets, two inline templates and favicon generated.')
