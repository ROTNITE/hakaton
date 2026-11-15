"""Assemble diagnostic render sheets and an offline inspection index."""
from pathlib import Path
import html
import json

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/3d-world/asset-library'
VIEWS = ['a', 'b', 'front', 'side', 'top', 'rear']


def main():
    sheets = OUT / 'sheets'
    sheets.mkdir(exist_ok=True)
    cards = []
    for path in sorted((OUT / 'reports').glob('*.json')):
        report = json.loads(path.read_text(encoding='utf-8'))
        images = [OUT / 'previews' / report['id'] / (v + '.png') for v in VIEWS]
        if not all(p.is_file() for p in images):
            continue
        canvas = Image.new('RGB', (1920, 1180), '#192329')
        draw = ImageDraw.Draw(canvas)
        draw.text((20, 10), report['id'] + ' / SOURCE AUDIT', fill='#e3ede9')
        for i, (image, view) in enumerate(zip(images, VIEWS)):
            x, y = i % 3 * 640, i // 3 * 570 + 35
            with Image.open(image) as picture:
                canvas.paste(picture.convert('RGB'), (x, y))
            draw.text((x + 12, y + 10), view, fill='white')
        canvas.save(sheets / (report['id'] + '.jpg'), quality=90)
        tris = sum(o.get('triangles', 0) for o in report['objects'])
        desc = f"{tris:,} triangles; {len(report['materials'])} materials; {len(report['actions'])} actions"
        cards.append(f'<article><h2>{html.escape(report["id"])}</h2><p>{desc}</p>'
                     f'<p>{html.escape(report["source"])}</p><a href="reports/{path.name}">Full report</a>'
                     f'<a href="sheets/{report["id"]}.jpg"><img loading="lazy" src="sheets/{report["id"]}.jpg"></a></article>')
    (OUT / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>MetaRescue asset inspection</title>'
        '<style>body{background:#111b20;color:#e3ede9;font:16px system-ui;margin:32px auto;max-width:1400px}'
        'h1{font-size:36px}article{border-top:1px solid #3c5059;padding:20px 0}img{width:100%}a{color:#a8d9bd}'
        'p{overflow-wrap:anywhere;color:#b7c7ca}</style><h1>Source model inspection</h1>'
        '<p>Original geometry and materials. These renders document defects before preparation.</p>'
        '<p><a href="prepared.html">Prepared v2 library and operating poses</a></p>' + ''.join(cards), encoding='utf-8')
    prepared=[]
    for file in sorted((ROOT/'blender/prepared/v2').glob('*/asset.json')):
        asset=json.loads(file.read_text(encoding='utf-8'))
        ident=asset['id'];preview=OUT/'previews'/('Repaired_'+ident)
        images=''.join(f'<a href="previews/Repaired_{ident}/{view}.png"><img loading="lazy" src="previews/Repaired_{ident}/{view}.png"></a>'
                       for view in ['a','b','front','side','top','rear','operating'] if (preview/(view+'.png')).exists())
        repairs=''.join('<li>'+html.escape(str(item))+'</li>' for item in asset.get('repairs',[]))
        prepared.append(f'<article><h2>{ident}</h2><p>{len(asset["parts"])} separate parts; '
            f'{sum(p["triangles"] for p in asset["parts"]):,} triangles</p>'
            f'<p><a href="../../../blender/prepared/v2/{ident}/{asset["blend"]}">Editable Blender file</a> · '
            f'<a href="../../../blender/prepared/v2/{ident}/asset.json">Part and material manifest</a></p>'
            f'<ul>{repairs}</ul><div class="views">{images}</div></article>')
    (OUT/'prepared.html').write_text('<!doctype html><meta charset="utf-8"><title>MetaRescue prepared v2</title>'
        '<style>body{background:#142127;color:#e3ede9;font:16px system-ui;margin:32px auto;max-width:1400px}'
        'article{border-top:1px solid #3c5059;padding:20px 0}a{color:#a8d9bd}.views{display:grid;grid-template-columns:repeat(3,1fr)}'
        'img{width:100%}li{margin:8px 0}</style><h1>Prepared library v2</h1><p>Editable derivatives; original sources preserved. '
        'Operating images are Blender action poses. Actual game motion is verified separately in Unreal.</p>'
        '<p><a href="index.html">Original source inspection</a></p>'+''.join(prepared),encoding='utf-8')
    print('MR_GALLERY', len(cards), 'complete six-view source sheets')


if __name__ == '__main__':
    main()
