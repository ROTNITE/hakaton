"""Export the local reference catalogue and prompt files from specs.json.

Standard library only. Images are copied from image_gen outputs, never edited here.
Run: python -B docs/assets/3d-asset-catalog-v1/build_catalog.py
"""

from pathlib import Path
import hashlib
import html
import json
import struct
import zipfile


ROOT = Path(__file__).resolve().parent


def main():
    spec = json.loads((ROOT / "specs.json").read_text(encoding="utf-8-sig"))
    assets = spec["assets"]
    assert len(assets) == 20 and len({a["id"] for a in assets}) == 20
    image_prompts = ROOT / "image-prompts"
    model_prompts = ROOT / "model-prompts"
    image_prompts.mkdir(exist_ok=True)
    model_prompts.mkdir(exist_ok=True)
    cards, contents, markdown, manifest = [], [], [], []
    intro = (
        "20 моделей, у каждой три ракурса на одном листе. "
        "Сгенерировано встроенным image_gen 9 ноября 2026 года. "
        "Это визуальные референсы для подготовки ассетов; 3D-сеток в комплекте нет."
    )
    usage = (
        "Для image-to-3D приложите лист выбранного объекта и используйте промпт «3D-модель». "
        "Если сервис принимает только одно изображение, начните с наиболее информативного ракурса; "
        "остальные используйте для проверки. Поддержка нескольких видов, отдельных деталей, "
        "скелета и формата экспорта зависит от сервиса. Размеры ниже — проектные ориентиры: "
        "генеративная картинка не является точным размерным чертежом. Перед Unreal проверяем "
        "масштаб, сетку, проёмы, материалы, подвижные части, коллизии и крепления. "
        "У повторяющихся видов возможны небольшие расхождения деталей; их согласуем на 3D-модели."
    )
    markdown.extend([
        "# MetaRescue — референсы 3D-ассетов v1", "", intro, "", usage, "",
        "[Открыть HTML-каталог](index.html)", "",
        "Промпты на английском. image-prompts — точные исходные промпты изображений; "
        "model-prompts — отдельное техническое задание на геометрию.", "",
        "Док-станция относится к будущей 3D-инфраструктуре; правила зарядки 2D-бенчмарка не меняются.", "",
        "## Состав", "",
    ])
    for asset in assets:
        ident = asset["id"]
        title = asset["title_ru"]
        image_rel = asset["reference_sheet"]
        image_path = ROOT / image_rel
        raw = image_path.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n", image_rel
        width, height = struct.unpack(">II", raw[16:24])
        assert width >= 1024 and height >= 768, image_rel
        assert len(asset["views_ru"]) == 3
        for kind, folder in (("image", image_prompts), ("model", model_prompts)):
            (folder / (ident + ".txt")).write_text(asset[kind + "_prompt"] + "\n", encoding="utf-8")
        views = " / ".join(asset["views_ru"])
        extra_html = ""
        if "image_refinement_prompt" in asset:
            refinement = asset["image_refinement_prompt"]
            (image_prompts / (ident + "-refinement.txt")).write_text(refinement + "\n", encoding="utf-8")
            assert (ROOT / asset["refinement_reference"]).is_file()
            extra_html = (
                '<details><summary>Правка второго ракурса носилок</summary><p>'
                'Итоговый лист получен после этой правки. '
                f'<a href="{asset["refinement_reference"]}">Исходный лист</a>.</p>'
                f'<pre>{html.escape(refinement)}</pre></details>'
            )
        contents.append(
            f'<a class="jump" href="#{ident}"><span>{ident[:2]}</span>{html.escape(title)}</a>'
        )
        details = []
        for kind, label, folder in (
            ("model", "Промпт: 3D-модель", "model-prompts"),
            ("image", "Промпт: изображение", "image-prompts"),
        ):
            details.append(
                f'<details {"open" if kind == "model" else ""}><summary>{label}</summary>'
                '<div class="prompt-actions">'
                f'<button type="button" data-copy="{ident}-{kind}">Копировать</button>'
                f'<a href="{folder}/{ident}.txt" download>Скачать TXT</a></div>'
                f'<pre id="{ident}-{kind}">{html.escape(asset[kind + "_prompt"])}</pre></details>'
            )
        cards.append(
            f'<article id="{ident}" class="asset"><header class="asset-head">'
            f'<div><div class="eyebrow">{html.escape(asset["priority_ru"])} · {ident[:2]} / 20</div>'
            f'<h2>{html.escape(title)}</h2></div>'
            f'<span class="size">{html.escape(asset["dimensions_target"])}</span></header>'
            f'<a href="{image_rel}" target="_blank" rel="noopener">'
            f'<img src="{image_rel}" width="{width}" height="{height}" loading="lazy" '
            f'alt="{html.escape(title)}: три ракурса"></a>'
            f'<p class="caption">Слева направо: {html.escape(views)}. '
            f'<a href="{image_rel}" download>PNG в исходном разрешении</a></p>'
            + "".join(details) + extra_html + '<a class="back" href="#catalog">К списку моделей ↑</a></article>'
        )
        markdown.append(f'- [{ident[:2]}. {title}](#{ident})')
        manifest.append({
            "id": ident, "image": image_rel, "width": width, "height": height,
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "views": 3,
        })
    markdown.extend([""])
    for asset in assets:
        ident, title = asset["id"], asset["title_ru"]
        markdown.extend([
            f'<a id="{ident}"></a>', "", f'## {ident[:2]}. {title}', "",
            f'Приоритет: {asset["priority_ru"]}. Размер-ориентир: {asset["dimensions_target"]}.', "",
            f'![{title}: три ракурса]({asset["reference_sheet"]})', "",
            "Слева направо: " + "; ".join(asset["views_ru"]) + ".", "",
            "### Промпт для 3D-модели", "", "```text", asset["model_prompt"], "```", "",
            "### Промпт для изображения", "", "```text", asset["image_prompt"], "```", "",
        ])
        if "image_refinement_prompt" in asset:
            markdown.extend([
                "Правка второго ракурса носилок. Сначала сгенерирован исходный лист, затем применён промпт:", "",
                "```text", asset["image_refinement_prompt"], "```", "",
                f'[Исходный лист для правки]({asset["refinement_reference"]})', "",
            ])
    stylesheet = """
    :root{color-scheme:light;--ink:#193438;--accent:#b65023;--line:#d7dfdc}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f2f4ef;color:var(--ink);font:16px/1.6 system-ui,Segoe UI,sans-serif}
    main{max-width:1200px;margin:auto;padding:48px 24px 80px}.hero{padding:0 0 24px}.eyebrow{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#52716c}
    h1{font-size:clamp(30px,5vw,52px);line-height:1.13;margin:12px 0 22px;letter-spacing:-.035em}h2{font-size:27px;line-height:1.25;margin:4px 0}
    p{max-width:95ch}a{color:#285e5d;text-underline-offset:3px}.lead{font-size:19px}.notice{border-left:3px solid var(--accent);padding:12px 18px;background:#fff9ef}
    nav{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:32px 0}.jump{display:flex;gap:12px;align-items:center;padding:11px 12px;border:1px solid var(--line);border-radius:6px;text-decoration:none;font-size:14px;background:#fff}
    .jump span{font-size:12px;color:var(--accent);font-weight:750}.jump:hover{border-color:#59817b}.asset{background:white;border:1px solid var(--line);border-radius:12px;margin:28px 0;overflow:hidden;scroll-margin-top:18px}
    .asset-head{display:flex;justify-content:space-between;gap:20px;align-items:center;padding:25px 28px}.size{font-size:14px;white-space:nowrap;color:#58706c}
    img{display:block;width:100%;height:auto}.caption{padding:12px 28px;font-size:13px;color:#526863;margin:0;border-bottom:1px solid var(--line);max-width:none}
    details{margin:16px 28px;border:1px solid var(--line);border-radius:6px;overflow:hidden}summary{padding:12px 16px;cursor:pointer;font-weight:650;background:#f7f9f6}
    pre{margin:0;padding:18px;white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.65 ui-monospace,Consolas,monospace;background:#f9fbf8;color:#243e3e}details p{padding:0 18px}
    .prompt-actions{display:flex;align-items:center;gap:16px;padding:10px 16px;border-top:1px solid var(--line);font-size:13px}button{font:inherit;border:1px solid #97b2aa;background:#fff;color:var(--ink);padding:6px 12px;border-radius:5px;cursor:pointer}button:hover{background:#edf5f0}.back{display:inline-block;font-size:13px;margin:3px 28px 24px}
    footer{font-size:13px;color:#617771;margin-top:36px}@media(max-width:800px){nav{grid-template-columns:repeat(2,minmax(0,1fr))}.asset-head{align-items:flex-start;flex-direction:column;gap:8px}main{padding:28px 12px}details{margin:12px}.caption{padding:12px}h2{font-size:23px}}
    @media print{nav,button,.back{display:none}.asset{break-inside:avoid}main{padding:0}details{display:block}pre{font-size:10px}}
    """
    script = """
    document.addEventListener('click', async event => {
      const button=event.target.closest('button[data-copy]'); if(!button)return;
      const text=document.getElementById(button.dataset.copy).textContent;
      try {
        await navigator.clipboard.writeText(text); button.textContent='Скопировано';
      } catch {
        const area=document.createElement('textarea');area.value=text;document.body.append(area);area.select();
        const ok=document.execCommand('copy');area.remove();button.textContent=ok?'Скопировано':'Выделите текст ниже';
      }
      setTimeout(()=>button.textContent='Копировать',2200);
    });
    """
    page = (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>MetaRescue — каталог 3D-ассетов</title><style>' + stylesheet + '</style></head><body><main>'
        '<header class="hero" id="catalog"><div class="eyebrow">MetaEvolution Rescue · Asset reference v1</div>'
        '<h1>Модели для спасательного квартала</h1>'
        f'<p class="lead">{html.escape(intro)}</p><p class="notice">{html.escape(usage)}</p>'
        '<p><a href="BLENDER_PROMPTS.md">Промпты для Blender / Unreal</a> · '
        '<a href="README.md">Полный каталог в Markdown</a> · '
        '<a href="specs.json">Все спецификации и промпты JSON</a></p>'
        '</header><nav aria-label="Список моделей">' + ''.join(contents) + '</nav>' + ''.join(cards)
        + '<footer>Локальный каталог без внешних ресурсов. '
        'Док-станция — задел для 3D-инфраструктуры; 2D-бенчмарки не изменены. '
        'Экспорт каталога: python -B build_catalog.py. Источник: specs.json.</footer>'
        + '<script>' + script + '</script></main></body></html>'
    )
    (ROOT / 'index.html').write_text(page, encoding='utf-8')
    (ROOT / 'README.md').write_text('\n'.join(markdown), encoding='utf-8')
    blender_prompts = [
        '# MetaRescue — промпты для Blender и Unreal Engine', '',
        'Каждый блок ниже — самостоятельный промпт для другой ИИ. '
        'Приложите соответствующий лист из трёх ракурсов. '
        'Ожидаемый результат: редактируемый .blend, FBX и PBR-текстуры. '
        'Возможность риггинга, разделения деталей и экспорта зависит от выбранного инструмента.', '',
    ]
    for asset in assets:
        blender_prompts.extend([
            '## ' + asset['id'][:2] + '. ' + asset['title_ru'], '',
            '[Референс: три ракурса](' + asset['reference_sheet'] + ')', '',
            '[Самостоятельный TXT](model-prompts/' + asset['id'] + '.txt)', '',
            '```text', asset['model_prompt'], '```', '',
        ])
    (ROOT / 'BLENDER_PROMPTS.md').write_text('\n'.join(blender_prompts), encoding='utf-8')
    report = {
        'selected_sheets': len(manifest), 'reference_views': sum(a['views'] for a in manifest),
        'prompt_files': len(list(image_prompts.glob('*.txt'))) + len(list(model_prompts.glob('*.txt'))),
        'generator': 'built-in image_gen', 'assets': manifest,
    }
    (ROOT / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    archive = ROOT.parent / 'MetaRescue-3D-asset-catalog-v1.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(ROOT.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts:
                bundle.write(file, 'MetaRescue-3D-asset-catalog-v1/' + file.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    print(json.dumps({k:v for k,v in report.items() if k != 'assets'}, ensure_ascii=False))
    print('ZIP:', archive)


if __name__ == '__main__':
    main()
