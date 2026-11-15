# MetaRescue — референсы 3D-ассетов v1

20 моделей, у каждой три ракурса на одном листе. Сгенерировано встроенным image_gen 9 ноября 2026 года. Это визуальные референсы для подготовки ассетов; 3D-сеток в комплекте нет.

Для image-to-3D приложите лист выбранного объекта и используйте промпт «3D-модель». Если сервис принимает только одно изображение, начните с наиболее информативного ракурса; остальные используйте для проверки. Поддержка нескольких видов, отдельных деталей, скелета и формата экспорта зависит от сервиса. Размеры ниже — проектные ориентиры: генеративная картинка не является точным размерным чертежом. Перед Unreal проверяем масштаб, сетку, проёмы, материалы, подвижные части, коллизии и крепления. У повторяющихся видов возможны небольшие расхождения деталей; их согласуем на 3D-модели.

[Открыть HTML-каталог](index.html)

Промпты на английском. image-prompts — точные исходные промпты изображений; model-prompts — отдельное техническое задание на геометрию.

Док-станция относится к будущей 3D-инфраструктуре; правила зарядки 2D-бенчмарка не меняются.

## Состав

- [01. Гусеничный эвакуатор](#01-rescue-rover)
- [02. Дрон-разведчик](#02-scout-drone)
- [03. Спасательные носилки](#03-rescue-stretcher)
- [04. Спасательный манекен](#04-training-mannequin)
- [05. Повреждённое здание](#05-damaged-building)
- [06. Модуль стены с окном](#06-window-wall)
- [07. Модуль стены с проходом](#07-doorway-wall)
- [08. Обломок бетонной плиты](#08-concrete-slab)
- [09. Статический завал](#09-brick-rubble-pile)
- [10. Деформированная стальная балка](#10-bent-steel-beam)
- [11. Секция дороги с тротуаром](#11-road-section)
- [12. Медицинский пункт](#12-medical-container)
- [13. Ретранслятор связи](#13-relay-mast)
- [14. Док-станция эвакуатора](#14-docking-station)
- [15. Стационарный сенсорный узел](#15-sensor-node)
- [16. Бетонный дорожный барьер](#16-road-barrier)
- [17. Уличный фонарь](#17-street-lamp)
- [18. Секция ограждения](#18-fence-section)
- [19. Ящик спасательного оборудования](#19-equipment-crate)
- [20. Служебный медицинский фургон](#20-medical-van)

<a id="01-rescue-rover"></a>

## 01. Гусеничный эвакуатор

Приоритет: Основной. Размер-ориентир: 2.5 × 1.35 × 1.5 м.

![Гусеничный эвакуатор: три ракурса](images/01-rescue-rover.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Гусеничный эвакуатор
VISUAL DESIGN: A low, wide, civilian tracked rescue transport robot, overall 2.5 m long and 1.35 m wide. Matte rescue-orange body panels on a charcoal undercarriage. Two continuous black rubber tracks, six clearly spaced road wheels per side. A long EMPTY 2.05 m stretcher cradle centered on top, brushed-metal side guides and two restrained locking clamps. The rear loading gate is CLOSED and vertical; visible rear hinge and compact winch under the cradle. A short black sensor mast at the FRONT LEFT corner stays clear of the full stretcher loading space, small front headlights and recessed camera. Rugged practical manufacturing, modest wear, no turret.
TARGET DIMENSIONS: 2.5 × 1.35 × 1.5 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate chassis, left/right track belts, wheel sets, stretcher cradle, rear hinged ramp, winch, sensor mast and lights. Center pivots on wheels and ramp hinge. Keep the cradle empty. Forward is toward the headlights; loading is from the rear. Preserve clearances and do not merge tracks with chassis. Rigid hard-surface parts suitable for later suspension/contact setup; do not simulate individual track links.
MECHANICAL CLEARANCE: the internal stretcher bay must provide at least 2.15 m length and 0.72 m width, so the separate 2.05 x 0.62 m stretcher fits without intersecting rails or mast. Keep loading ramp a separate hinged mesh; provide a simple animation or clear open/closed transforms if supported, but do not claim winch/physics is functioning.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: A low, wide, civilian tracked rescue transport robot, overall 2.5 m long and 1.35 m wide. Matte rescue-orange body panels on a charcoal undercarriage. Two continuous black rubber tracks, six clearly spaced road wheels per side. A long EMPTY 2.05 m stretcher cradle centered on top, brushed-metal side guides and two restrained locking clamps. The rear loading gate is CLOSED and vertical; visible rear hinge and compact winch under the cradle. A short black sensor mast at the FRONT LEFT corner stays clear of the full stretcher loading space, small front headlights and recessed camera. Rugged practical manufacturing, modest wear, no turret.
```

<a id="02-scout-drone"></a>

## 02. Дрон-разведчик

Приоритет: Основной. Размер-ориентир: 1.3 × 1.3 × 0.45 м.

![Дрон-разведчик: три ракурса](images/02-scout-drone.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Дрон-разведчик
VISUAL DESIGN: A professional civilian search-and-rescue quadcopter, four arms in an X arrangement, exactly four motors and four separate TWO-BLADE propellers. Compact matte desaturated-blue central fuselage, charcoal arms, dark metallic motor housings. One small spherical downward-front camera on a two-axis gimbal beneath the nose. Two short landing skids, a recessed battery pack, small practical navigation lamps. No payload, no weapons, no propeller guards. Consistent industrial design matching an orange rescue rover.
TARGET DIMENSIONS: 1.3 × 1.3 × 0.45 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate central body, four arms, four motors, four propellers, camera gimbal axes, camera and landing skids. Align propeller pivots with motor axes. Preserve rotor clearance and camera view. Prepare rigid components for thrust-driven flight; no baked rotor motion blur.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: A professional civilian search-and-rescue quadcopter, four arms in an X arrangement, exactly four motors and four separate TWO-BLADE propellers. Compact matte desaturated-blue central fuselage, charcoal arms, dark metallic motor housings. One small spherical downward-front camera on a two-axis gimbal beneath the nose. Two short landing skids, a recessed battery pack, small practical navigation lamps. No payload, no weapons, no propeller guards. Consistent industrial design matching an orange rescue rover.
```

<a id="03-rescue-stretcher"></a>

## 03. Спасательные носилки

Приоритет: Основной. Размер-ориентир: 2.05 × 0.62 × 0.18 м.

![Спасательные носилки: три ракурса](images/03-rescue-stretcher-v2.png)

Слева направо: Сверху спереди, 3/4; Снизу, 3/4; Боковой профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Спасательные носилки
VISUAL DESIGN: One EMPTY low-profile rescue stretcher designed to slide into a robotic transport cradle. A narrow rectangular brushed-aluminum tubular frame, softly rounded corners, four recessed carrying handles, dark charcoal fabric bed with a muted teal washable padded insert, three unfastened orange restraint straps laid neatly within the bed. Two parallel low skids beneath the frame, small metal front/rear latch fittings. No folding legs and no hospital trolley wheels. Entire object is slim, robust, utilitarian.
TARGET DIMENSIONS: 2.05 × 0.62 × 0.18 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate rigid frame, bed insert, three restraint straps, two underside skids and latch fittings. Keep real-world adult scale and alignment with a 2.05 m rover cradle. Empty stretcher, no patient. Fabric may initially be static; moving straps can be rigged later.
REFERENCE NOTE: the middle panel is an underside three-quarter view, revealing both longitudinal sliding skids. Overall stretcher dimensions include handles and outer rim; it must fit the rover bay without intersection.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One EMPTY low-profile rescue stretcher designed to slide into a robotic transport cradle. A narrow rectangular brushed-aluminum tubular frame, softly rounded corners, four recessed carrying handles, dark charcoal fabric bed with a muted teal washable padded insert, three unfastened orange restraint straps laid neatly within the bed. Two parallel low skids beneath the frame, small metal front/rear latch fittings. No folding legs and no hospital trolley wheels. Entire object is slim, robust, utilitarian.
```

Правка второго ракурса носилок. Сначала сгенерирован исходный лист, затем применён промпт:

```text
Use case: precise-object-edit. Edit the supplied three-panel rescue stretcher reference sheet. Preserve the EXACT stretcher design, charcoal fabric shell, brushed metal rim, teal cushion, three orange straps, sizes, gray background and panel layout. Keep LEFT panel and RIGHT side-profile panel unchanged. Change ONLY the CENTER panel to a genuinely different underside three-quarter view from the opposite end, clearly revealing the TWO underside longitudinal sliding skids, underside frame and opposite-end latch fittings. In the center the stretcher is displayed tilted on its side so the camera sees the bottom, with no extra supports or extra parts. Three views must show the same object. No labels, text, watermark, people or wheels.
```

[Исходный лист для правки](references/03-rescue-stretcher-initial.png)

<a id="04-training-mannequin"></a>

## 04. Спасательный манекен

Приоритет: Основной. Размер-ориентир: Рост 1.75 м.

![Спасательный манекен: три ракурса](images/04-training-mannequin.png)

Слева направо: Спереди, 3/4; Сзади, 3/4; Боковой профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Спасательный манекен
VISUAL DESIGN: One adult-size non-graphic rescue training mannequin, anatomically proportionate human silhouette, matte muted terracotta-red polymer surface with subtle joint seams. Neutral feature-minimal face, solid closed surface, no exposed machinery. Full body standing upright in a relaxed A-pose, arms angled 25 degrees from torso, palms facing inward, feet hip-width apart. Same fixed pose in all three panels. Simple practical training dummy, no clothing, no blood, no injuries, no base.
TARGET DIMENSIONS: Рост 1.75 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Create one connected human mannequin character in the depicted relaxed A-pose, adult 1.75 m scale. Clean deformation-friendly topology around shoulders, elbows, hips and knees; separate fingers only if practical. Preserve symmetrical limb lengths and closed surfaces. A humanoid skeleton is desirable if supported, otherwise deliver neutral mesh for later rigging. Do not combine multiple views as three characters.
RIG: provide a simple humanoid armature with pelvis, spine, head, arm and leg chains, clean skin weights and a neutral A-pose if the tool supports rigging. Do not leave a Blender-only control system as the only exported skeleton. A lying pose may be included as a separate pose/action, not a second mesh.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
View override for the mannequin ONLY: left exact front view, center exact rear view, right exact right-side profile. Keep the same relaxed A-pose.
Subject: One adult-size non-graphic rescue training mannequin, anatomically proportionate human silhouette, matte muted terracotta-red polymer surface with subtle joint seams. Neutral feature-minimal face, solid closed surface, no exposed machinery. Full body standing upright in a relaxed A-pose, arms angled 25 degrees from torso, palms facing inward, feet hip-width apart. Same fixed pose in all three panels. Simple practical training dummy, no clothing, no blood, no injuries, no base.
```

<a id="05-damaged-building"></a>

## 05. Повреждённое здание

Приоритет: Основной. Размер-ориентир: 12 × 10 × 10 м.

![Повреждённое здание: три ракурса](images/05-damaged-building.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Повреждённое здание
VISUAL DESIGN: A single compact three-storey civilian concrete-and-faded-brick building shell after an earthquake. Rectangular footprint 12 by 10 m, three storeys each approximately 3.2 m high. Flat roof partly missing, one front corner is broken away to expose THREE distinct floor levels, substantial concrete columns, beams and floor slabs with thickness. Ground floor has a wide open entry and accessible interior. Window bays regular, restrained chipped plaster, muted gray concrete and dusty red-brown brick infill. Mostly intact rear facade. Damage identical across all views, with a distinctive diagonal break at the front-right corner. No surrounding debris pile and no ground terrain.
TARGET DIMENSIONS: 12 × 10 × 10 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Deliver a building assembly with separately named structural columns, beams, slabs, wall panels and roof sections. Preserve open doorways and empty room volumes. Closed thickness on damaged parts and exposed cuts. Do not merge everything into one solid bounding block. Keep visible floors at consistent heights; structure is static until selected components are configured for destruction. No simulated structural engineering claims.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: A single compact three-storey civilian concrete-and-faded-brick building shell after an earthquake. Rectangular footprint 12 by 10 m, three storeys each approximately 3.2 m high. Flat roof partly missing, one front corner is broken away to expose THREE distinct floor levels, substantial concrete columns, beams and floor slabs with thickness. Ground floor has a wide open entry and accessible interior. Window bays regular, restrained chipped plaster, muted gray concrete and dusty red-brown brick infill. Mostly intact rear facade. Damage identical across all views, with a distinctive diagonal break at the front-right corner. No surrounding debris pile and no ground terrain.
```

<a id="06-window-wall"></a>

## 06. Модуль стены с окном

Приоритет: Основной. Размер-ориентир: 3 × 0.3 × 3.2 м.

![Модуль стены с окном: три ракурса](images/06-window-wall.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Модуль стены с окном
VISUAL DESIGN: One standalone rectangular modular exterior wall panel, 3.0 m wide, 3.2 m high and 0.30 m thick. Weathered pale-gray concrete frame with faded red-brown brick infill, one centered EMPTY rectangular window opening, chipped off-white plaster on the exterior and plain dusty plaster on the interior. A small chipped upper-right corner reveals the material thickness but keeps the panel largely rectangular for modular assembly. No glass, no floor, no surrounding building.
TARGET DIMENSIONS: 3 × 0.3 × 3.2 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: One reusable modular wall with a genuine open window and 0.30 m thickness. Separate plaster/brick/concrete material regions; intact planar side edges for snapping. Keep front/back connected around opening with closed surfaces. Pivot at bottom-left of the exterior face. Do not fill the opening with invisible geometry.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One standalone rectangular modular exterior wall panel, 3.0 m wide, 3.2 m high and 0.30 m thick. Weathered pale-gray concrete frame with faded red-brown brick infill, one centered EMPTY rectangular window opening, chipped off-white plaster on the exterior and plain dusty plaster on the interior. A small chipped upper-right corner reveals the material thickness but keeps the panel largely rectangular for modular assembly. No glass, no floor, no surrounding building.
```

<a id="07-doorway-wall"></a>

## 07. Модуль стены с проходом

Приоритет: Основной. Размер-ориентир: 3 × 0.3 × 3.2 м.

![Модуль стены с проходом: три ракурса](images/07-doorway-wall.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Модуль стены с проходом
VISUAL DESIGN: One standalone modular building wall panel with a broad open ground-floor doorway: 3.0 m total width, 3.2 m height, 0.30 m thickness, central doorway approximately 1.7 m wide and 2.4 m high. Pale concrete jambs and lintel, dusty faded red-brown brick infill and chipped off-white plaster matching an earthquake-damaged civilian block. The doorway reaches the bottom edge, no sill, no door leaf, absolutely no obstruction across the opening.
TARGET DIMENSIONS: 3 × 0.3 × 3.2 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Reusable wall module with open doorway wide enough for a 1.35 m rover with clearance. Genuine opening, no hidden crossbar or full-panel collision mesh in the doorway. Closed mesh thickness on jambs/lintel. Modular snapping dimensions and bottom-corner pivot. Same materials and wall thickness as window wall.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One standalone modular building wall panel with a broad open ground-floor doorway: 3.0 m total width, 3.2 m height, 0.30 m thickness, central doorway approximately 1.7 m wide and 2.4 m high. Pale concrete jambs and lintel, dusty faded red-brown brick infill and chipped off-white plaster matching an earthquake-damaged civilian block. The doorway reaches the bottom edge, no sill, no door leaf, absolutely no obstruction across the opening.
```

<a id="08-concrete-slab"></a>

## 08. Обломок бетонной плиты

Приоритет: Основной. Размер-ориентир: 2.8 × 1.6 × 0.25 м.

![Обломок бетонной плиты: три ракурса](images/08-concrete-slab.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Обломок бетонной плиты
VISUAL DESIGN: One SINGLE detached broken reinforced-concrete floor slab fragment, roughly 2.8 m long, 1.6 m wide and 0.25 m thick, asymmetric pentagonal outline. Two long edges are straight former construction edges; the opposite corner is diagonally fractured, exposing a few short dull rusted reinforcing rods. Rough gray concrete aggregate and pale dusty top surface, closed substantial thickness. The slab rests flat. Exactly the same fracture silhouette and rod positions from all three angles. No loose debris surrounding it.
TARGET DIMENSIONS: 2.8 × 1.6 × 0.25 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: One physical slab fragment with closed watertight concrete body and separate short reinforcement rods. Keep obvious solid thickness and irregular fracture surface. Suitable for later convex collision decomposition; do not make a paper-thin plane. No cluster of many unrelated stones.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One SINGLE detached broken reinforced-concrete floor slab fragment, roughly 2.8 m long, 1.6 m wide and 0.25 m thick, asymmetric pentagonal outline. Two long edges are straight former construction edges; the opposite corner is diagonally fractured, exposing a few short dull rusted reinforcing rods. Rough gray concrete aggregate and pale dusty top surface, closed substantial thickness. The slab rests flat. Exactly the same fracture silhouette and rod positions from all three angles. No loose debris surrounding it.
```

<a id="09-brick-rubble-pile"></a>

## 09. Статический завал

Приоритет: Основной. Размер-ориентир: 3 × 2 × 0.8 м.

![Статический завал: три ракурса](images/09-brick-rubble-pile.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Статический завал
VISUAL DESIGN: One compact low rubble pile as a single reusable environment prop, footprint 3 by 2 m and height 0.8 m, made of dusty faded red bricks, irregular pale concrete chunks and broken plaster. A distinctive broad pale concrete fragment lies at one end, small red bricks fill the center, gently tapered outer silhouette. No vegetation, pipes, timber, wires, surrounding terrain or floating pieces. Same stone and brick arrangement in every view. Ground contact at a flat baseline.
TARGET DIMENSIONS: 3 × 2 × 0.8 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: A reusable static rubble-pile asset with a coherent underside and no distant scattered fragments. Visible major pieces can remain separate if supported but this asset is intended mainly as fixed blockage, not hundreds of active physics bodies. Preserve outer obstacle silhouette for a simplified collision proxy. No ground plane included.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One compact low rubble pile as a single reusable environment prop, footprint 3 by 2 m and height 0.8 m, made of dusty faded red bricks, irregular pale concrete chunks and broken plaster. A distinctive broad pale concrete fragment lies at one end, small red bricks fill the center, gently tapered outer silhouette. No vegetation, pipes, timber, wires, surrounding terrain or floating pieces. Same stone and brick arrangement in every view. Ground contact at a flat baseline.
```

<a id="10-bent-steel-beam"></a>

## 10. Деформированная стальная балка

Приоритет: Основной. Размер-ориентир: Длина 3 м.

![Деформированная стальная балка: три ракурса](images/10-bent-steel-beam.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Деформированная стальная балка
VISUAL DESIGN: One single detached steel I-beam approximately 3 m long, dark oxidized gray with limited dull rust. Clearly recognizable I-shaped cross section, modest 15-degree bend near the middle, intact flanges and web with plausible metal thickness. One end is cleanly cut, the other end slightly torn. Lying horizontally with one flange touching the floor. No concrete, chains, bolts, other beams or surrounding rubble.
TARGET DIMENSIONS: Длина 3 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: One closed thick steel I-beam, separate from any ground. Preserve the I cross section through the gentle deformation. No zero-thickness faces. Center pivot useful for physics; prepare simplified collision separately after import. Do not weld the beam to a rubble pile.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One single detached steel I-beam approximately 3 m long, dark oxidized gray with limited dull rust. Clearly recognizable I-shaped cross section, modest 15-degree bend near the middle, intact flanges and web with plausible metal thickness. One end is cleanly cut, the other end slightly torn. Lying horizontally with one flange touching the floor. No concrete, chains, bolts, other beams or surrounding rubble.
```

<a id="11-road-section"></a>

## 11. Секция дороги с тротуаром

Приоритет: Основной. Размер-ориентир: 10 × 8 × 0.35 м.

![Секция дороги с тротуаром: три ракурса](images/11-road-section.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Секция дороги с тротуаром
VISUAL DESIGN: One isolated modular urban street cross-section segment 10 m long by 8 m wide: a 6 m asphalt carriageway between two 1 m pale-concrete sidewalks. Raised curbs about 0.15 m high, visible closed edges and shallow base thickness, no terrain beyond the rectangular module. Charcoal weathered asphalt with subtle cracks and one restrained faded dashed lane marking, dusty light-gray sidewalk paving. Both longitudinal ends are straight and match for tiling. No cars, buildings, signs, vegetation or props.
TARGET DIMENSIONS: 10 × 8 × 0.35 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Create an editable modular street section: separate asphalt road, two raised sidewalks and curbs, real step height, straight tileable ends, UVs for tileable materials. Cracks mostly material detail, selected deeper damage can be geometry later. Preserve a continuous physical driving surface. No lighting or shadows baked into albedo.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One isolated modular urban street cross-section segment 10 m long by 8 m wide: a 6 m asphalt carriageway between two 1 m pale-concrete sidewalks. Raised curbs about 0.15 m high, visible closed edges and shallow base thickness, no terrain beyond the rectangular module. Charcoal weathered asphalt with subtle cracks and one restrained faded dashed lane marking, dusty light-gray sidewalk paving. Both longitudinal ends are straight and match for tiling. No cars, buildings, signs, vegetation or props.
```

<a id="12-medical-container"></a>

## 12. Медицинский пункт

Приоритет: Основной. Размер-ориентир: 6 × 3 × 3 м.

![Медицинский пункт: три ракурса](images/12-medical-container.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Медицинский пункт
VISUAL DESIGN: One prefabricated civilian medical aid container, 6 m long by 3 m wide by 3 m high, muted teal painted steel exterior and off-white trims, flat roof with compact ventilation unit. At the front a wide 1.8 m open double-door entrance and a SHORT shallow metal access ramp, simple white medical plus symbol above the entrance, no writing. Minimal clean light interior visible through doorway. One small side window, utility cabinet on rear wall. Closed doors folded against facade. No ambulance, people, furniture outside or surrounding scene.
TARGET DIMENSIONS: 6 × 3 × 3 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate container shell, roof, open door leaves, access ramp, ventilation unit and rear cabinet. Actual passable entrance with interior floor and wall thickness, no solid facade behind opening. White plus is generic material/decal. Keep interior simple and preserve unloading/docking clearance. No baked interior illumination.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One prefabricated civilian medical aid container, 6 m long by 3 m wide by 3 m high, muted teal painted steel exterior and off-white trims, flat roof with compact ventilation unit. At the front a wide 1.8 m open double-door entrance and a SHORT shallow metal access ramp, simple white medical plus symbol above the entrance, no writing. Minimal clean light interior visible through doorway. One small side window, utility cabinet on rear wall. Closed doors folded against facade. No ambulance, people, furniture outside or surrounding scene.
```

<a id="13-relay-mast"></a>

## 13. Ретранслятор связи

Приоритет: Инфраструктура. Размер-ориентир: Высота 3.5 м.

![Ретранслятор связи: три ракурса](images/13-relay-mast.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Ретранслятор связи
VISUAL DESIGN: One compact portable civil emergency radio relay mast, 3.5 m tall: galvanized telescopic pole, three short stabilized folding legs, low dark-gray battery cabinet fixed at base, two slim off-white rectangular antenna panels near top and one small omnidirectional whip. A narrow muted teal band on the cabinet links it to the medical base. Practical cables neatly secured against mast. No satellite dish, screens, terrain, logos or surrounding props.
TARGET DIMENSIONS: Высота 3.5 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate base cabinet, folding support legs, mast sections and antenna panels. Keep a stable compact footprint and closed simple structural parts. Ground pivot at mast center. Antenna geometry is a visual component for later simulated communication; do not generate invisible radio effects.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One compact portable civil emergency radio relay mast, 3.5 m tall: galvanized telescopic pole, three short stabilized folding legs, low dark-gray battery cabinet fixed at base, two slim off-white rectangular antenna panels near top and one small omnidirectional whip. A narrow muted teal band on the cabinet links it to the medical base. Practical cables neatly secured against mast. No satellite dish, screens, terrain, logos or surrounding props.
```

<a id="14-docking-station"></a>

## 14. Док-станция эвакуатора

Приоритет: Инфраструктура. Размер-ориентир: 3 × 1.8 × 0.4 м.

![Док-станция эвакуатора: три ракурса](images/14-docking-station.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Док-станция эвакуатора
VISUAL DESIGN: One low ground-robot docking station: rectangular charcoal metal platform 3.0 m long and 1.8 m wide, shallow beveled entry lip, two low side guide rails and rear upright service housing no higher than 0.4 m. Brushed-metal charging contacts at rear, one slim teal status bar and restrained orange corner markings. The center is clear and physically wide enough for a tracked rover. EMPTY station, no robot, no cable across entry and no freestanding charger tower.
TARGET DIMENSIONS: 3 × 1.8 × 0.4 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate platform, guide rails, rear service housing and charging contacts. Real clearances for 1.35 m wide rover; flush or shallow-ramp entry. Closed mesh and ground-level pivot. This is a docking visual asset; battery/charging behavior is implemented separately in the environment and does not change the 2D benchmark rules.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One low ground-robot docking station: rectangular charcoal metal platform 3.0 m long and 1.8 m wide, shallow beveled entry lip, two low side guide rails and rear upright service housing no higher than 0.4 m. Brushed-metal charging contacts at rear, one slim teal status bar and restrained orange corner markings. The center is clear and physically wide enough for a tracked rover. EMPTY station, no robot, no cable across entry and no freestanding charger tower.
```

<a id="15-sensor-node"></a>

## 15. Стационарный сенсорный узел

Приоритет: Инфраструктура. Размер-ориентир: Высота 1.6 м.

![Стационарный сенсорный узел: три ракурса](images/15-sensor-node.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Стационарный сенсорный узел
VISUAL DESIGN: One civil rescue observation sensor on a short sturdy tripod, overall 1.6 m tall. Three dark metal legs, compact muted teal equipment housing, one small black camera lens at front and a short narrow antenna above. Small rectangular battery box mounted low between legs, no screens. Utility-grade realistic proportions, restrained wear. No scanner light beams, drones, separate cases or surroundings.
TARGET DIMENSIONS: Высота 1.6 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate tripod legs, central mast, equipment housing, camera head and battery. Camera pivot placed at lens rotation axis if separate. Keep lenses distinct material regions. Static infrastructure mesh with support footprint; sensor visibility and detection logic are configured later.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One civil rescue observation sensor on a short sturdy tripod, overall 1.6 m tall. Three dark metal legs, compact muted teal equipment housing, one small black camera lens at front and a short narrow antenna above. Small rectangular battery box mounted low between legs, no screens. Utility-grade realistic proportions, restrained wear. No scanner light beams, drones, separate cases or surroundings.
```

<a id="16-road-barrier"></a>

## 16. Бетонный дорожный барьер

Приоритет: Реквизит. Размер-ориентир: 2 × 0.6 × 0.85 м.

![Бетонный дорожный барьер: три ракурса](images/16-road-barrier.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Бетонный дорожный барьер
VISUAL DESIGN: One single freestanding precast concrete Jersey road barrier, 2 m long, 0.60 m wide at foot and 0.85 m high. Sloped sides, narrower top, two forklift recesses at bottom, chipped pale-gray concrete with worn diagonal orange-and-off-white safety stripes on upper broad faces. Same chips and stripes around the same object from all views. No legs, fence, signs, road, cones or extra barriers.
TARGET DIMENSIONS: 2 × 0.6 × 0.85 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: One closed solid barrier mesh with correctly modeled sloped cross section, thick base and forklift recesses. Material slots for concrete and painted bands. Suitable for static blockage or a heavy movable rigid body after mass/collision setup. No surrounding ground mesh.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One single freestanding precast concrete Jersey road barrier, 2 m long, 0.60 m wide at foot and 0.85 m high. Sloped sides, narrower top, two forklift recesses at bottom, chipped pale-gray concrete with worn diagonal orange-and-off-white safety stripes on upper broad faces. Same chips and stripes around the same object from all views. No legs, fence, signs, road, cones or extra barriers.
```

<a id="17-street-lamp"></a>

## 17. Уличный фонарь

Приоритет: Реквизит. Размер-ориентир: Высота 6 м.

![Уличный фонарь: три ракурса](images/17-street-lamp.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Уличный фонарь
VISUAL DESIGN: One contemporary civilian street light, 6 m tall, slim galvanized gray pole with square bolted base flange, one gently curved short upper arm holding a flat dark-gray LED luminaire. Subtle grime and limited paint wear at base. Lamp is OFF in daylight so geometry is clear. No cables dangling, road, signs, second light head or surrounding environment.
TARGET DIMENSIONS: Высота 6 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate pole, base plate, upper arm and lamp head, closed thickness and sensible segment counts. Ground pivot at base center. Emissive lens region separate for later lighting. Static environment asset; avoid extremely thin invisible geometry.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One contemporary civilian street light, 6 m tall, slim galvanized gray pole with square bolted base flange, one gently curved short upper arm holding a flat dark-gray LED luminaire. Subtle grime and limited paint wear at base. Lamp is OFF in daylight so geometry is clear. No cables dangling, road, signs, second light head or surrounding environment.
```

<a id="18-fence-section"></a>

## 18. Секция ограждения

Приоритет: Реквизит. Размер-ориентир: 3 × 0.12 × 1.8 м.

![Секция ограждения: три ракурса](images/18-fence-section.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Секция ограждения
VISUAL DESIGN: One freestanding modular industrial fence section 3 m wide and 1.8 m high, two square dark-gray steel posts with small base plates, rectangular steel frame filled by galvanized welded-wire mesh with medium clear spacing. Slight bent lower corner and modest surface wear, mostly intact. No gate, barbed wire, masonry, terrain, plants or adjoining panels. Rear is visibly the back of the same welded construction.
TARGET DIMENSIONS: 3 × 0.12 × 1.8 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate two posts, perimeter frame and mesh insert. Keep real holes in coarse wire grid where practical, or a masked material option as later optimization. Structural collision should be simplified independently; do not turn transparent visual openings into undocumented passable routes. Bottom-corner snapping pivot.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One freestanding modular industrial fence section 3 m wide and 1.8 m high, two square dark-gray steel posts with small base plates, rectangular steel frame filled by galvanized welded-wire mesh with medium clear spacing. Slight bent lower corner and modest surface wear, mostly intact. No gate, barbed wire, masonry, terrain, plants or adjoining panels. Rear is visibly the back of the same welded construction.
```

<a id="19-equipment-crate"></a>

## 19. Ящик спасательного оборудования

Приоритет: Реквизит. Размер-ориентир: 0.8 × 0.5 × 0.45 м.

![Ящик спасательного оборудования: три ракурса](images/19-equipment-crate.png)

Слева направо: Спереди, 3/4; Сзади, 3/4; Вид сзади.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Ящик спасательного оборудования
VISUAL DESIGN: One rugged closed civil rescue equipment case, 0.8 m long, 0.5 m wide and 0.45 m high. Muted teal molded hard shell with dark rubber corner protectors, two silver front latches, recessed carry handles on short ends, fitted closed lid. Moderate scuffs, a small plain white medical plus on lid, no writing, labels, weapons or extra contents. Same latch and handle positions in all views.
TARGET DIMENSIONS: 0.8 × 0.5 × 0.45 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate lower case shell, lid, two latches and carry handles if supported. Consistent hinge edge opposite latches, closed case in all references. UV/material regions for polymer, rubber and metal. Suitable as a movable rigid prop after collision/mass setup; no interior contents required.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One rugged closed civil rescue equipment case, 0.8 m long, 0.5 m wide and 0.45 m high. Muted teal molded hard shell with dark rubber corner protectors, two silver front latches, recessed carry handles on short ends, fitted closed lid. Moderate scuffs, a small plain white medical plus on lid, no writing, labels, weapons or extra contents. Same latch and handle positions in all views.
```

<a id="20-medical-van"></a>

## 20. Служебный медицинский фургон

Приоритет: Реквизит. Размер-ориентир: 5.5 × 2.1 × 2.5 м.

![Служебный медицинский фургон: три ракурса](images/20-medical-van.png)

Слева направо: Спереди слева, 3/4; Сзади справа, 3/4; Правый профиль.

### Промпт для 3D-модели

```text
You are creating an ACTUAL editable 3D asset in Blender for the MetaRescue Unreal Engine project. Use the attached three-view sheet as a visual reference for ONE object, not three copies. Produce geometry, not another render or an illustration.
Deliver: (1) a clean .blend file, (2) an FBX export, (3) all external PBR texture files in a textures folder. If the available tool cannot create these files, say exactly which deliverables remain unavailable.
Use meters in Blender, explicit real-world dimensions, and a verified unit conversion on FBX export (1 meter must become 100 Unreal centimeters). Keep vehicle forward direction and Z-up orientation consistent. Apply object scale/rotation before rigging where appropriate. Put the asset at the origin and use meaningful names for objects, materials and collections.
Match the moderately realistic contemporary civilian rescue style, silhouette and material colors of the reference. Prefer clean reusable game geometry, closed thickness on solid parts and real openings. Use sensible UVs and separate PBR base-color, roughness, metallic and normal maps as needed. Bake Blender-only procedural shaders into texture maps for export; do not bake lighting or contact shadows into base color.
Keep functional moving parts separate, with pivots at their actual hinge/rotation axes. Do not weld rotors, wheels, doors or loading mechanisms into the main body. Prepare simplified convex collision proxies for movable rigid parts where supported, separate from render geometry; preserve door/window passages when preparing static collisions. Rigging or collision setup may require a later pass and must not be claimed as verified without inspection.
Do not include studio background, floor plane, cameras, lights, labels, UI, extra objects or runtime gameplay logic in the exported asset. The .blend may contain a separate disabled preview collection, excluded from FBX.
Check dimensions, normals, missing textures, part names, pivots and FBX contents. Report polygon counts and explicitly list any unverified export/import steps.

ASSET: Служебный медицинский фургон
VISUAL DESIGN: One unbranded modern civilian medical support van with a short hood, high roof, white body, modest teal side band and small generic orange medical plus symbols. Four black rubber wheels with simple steel rims, dark windows with basic interior silhouette, sliding side door and double rear doors all CLOSED, restrained blue roof beacons switched OFF. Practical rescue support vehicle, light dust, no writing, logos, license plate characters, weapons or people.
TARGET DIMENSIONS: 5.5 × 2.1 × 2.5 м (simulation design targets).
REQUIRED GEOMETRY / PARTS: Separate body shell, four wheels with centered pivots, sliding side door, two rear door leaves, lights and glass. Simple interior is sufficient. Full-size 5.5 m van, not a toy. Used as static base scenery initially; do not bake it into road or ground. No branded badges.
```

### Промпт для изображения

```text
Use case: stylized-concept.
Asset type: a multi-view reference sheet for ONE model in an Unreal Engine civilian rescue simulation.
Primary request: create a polished photorealistic PBR 3D studio-render turnaround triptych. This is a model reference, NOT a scene illustration.
Scene/backdrop: uniform light neutral-gray seamless background in all panels, faint contact shadow only.
Composition/framing: ONE landscape image, approximately 3:2 aspect ratio, exactly THREE equal vertical panels in one horizontal row. Show the EXACT SAME SINGLE asset once in each panel, completely visible, evenly spaced with margins. LEFT: front-left three-quarter view. CENTER: rear-right three-quarter view showing the opposite end and opposite side. RIGHT: clean right-side profile. Same scale, geometry, mechanical state, materials and damage in all three views; do not mirror the object. Use near-orthographic long-lens cameras, no wide-angle distortion.
Style/medium: coherent moderately realistic game-production hard-surface asset, convincing materials and real-world proportions, industrial civilian rescue equipment. Subtle restrained wear. Soft neutral studio light, crisp readable surfaces, no dramatic shadows or depth-of-field blur.
Constraints: no dimension lines, no labels, no typography, no watermarks, no scene, no decorative accessories, no extra models, no floating separated parts, no weapons, no sci-fi, no people unless the subject is explicitly a mannequin. Repeating the same asset in three views is mandatory.
Subject: One unbranded modern civilian medical support van with a short hood, high roof, white body, modest teal side band and small generic orange medical plus symbols. Four black rubber wheels with simple steel rims, dark windows with basic interior silhouette, sliding side door and double rear doors all CLOSED, restrained blue roof beacons switched OFF. Practical rescue support vehicle, light dust, no writing, logos, license plate characters, weapons or people.
```
