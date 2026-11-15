# Дополнительные модели после проверки библиотеки

Для текущего физического этапа обязательных недостающих моделей нет. Эти три дополнения полезны для следующего художественного прохода; карта работает без них. Общий стиль: современный гражданский город, умеренно реалистичный PBR, приглушённая штукатурка/кирпич, практическое оборудование, без фантастики. Генерировать одну модель, не три копии из референса.

## 21. Небольшой городской магазин

Место: первые этажи двух сохранившихся кварталов. Даёт другой силуэт и понятный человеческий масштаб.

```text
Create an actual editable Blender game asset for Unreal Engine: one unbranded contemporary neighborhood corner shop, 9 x 6 x 3.5 meters. Muted cream plaster, restrained dark green metal trim, flat roof with parapet, three street-facing bays, a separate glass entrance door and two large transparent shop windows. Model wall thickness and a simple empty interior behind the windows. Separate frame and glazing; never fill the glass aperture with an opaque wall. No text or logos, no people, no street or floor plane outside the building. Target 15,000-30,000 triangles, metric units, Z up, applied scale, ground pivot, clean UVs. Deliver .blend, FBX and external PBR textures. Give the door a hinge pivot and an inspectable open/close action. Keep a clear 1.2 m doorway. Do not add gameplay code, cameras or lighting to the export.
```

## 22. Повреждённый гражданский автомобиль

Место: огороженный карман у разрушенного дома, за пределами проезжей части. Это источник перекрытия/контекст аварии, не новый тип спасательного робота.

```text
Create one editable low-poly contemporary civilian compact hatchback for Unreal Engine, unbranded, 4.1 x 1.75 x 1.5 meters. Desaturated gray-green paint, dust, one dented front fender and a cracked windshield, moderate earthquake debris damage, no fire or gore. Separate body, four wheels, front doors, rear hatch, glass and lights. Give windows actual transparent glazing and a simple dark interior; do not place opaque surfaces behind the glass apertures. Wheel pivots at axle centers, local wheel roll axes consistent. Target 20,000-35,000 triangles, meters, Z up, forward +X. Deliver an editable .blend, FBX, external base-color/roughness/metallic/normal textures and named wheel-roll and door-opening demonstration actions. No brand badges, readable plate characters, road, background, people or gameplay logic.
```

## 23. Набор городской растительности

Место: сохранённые дворы и край базы. Помогает отличать жилую часть от повреждённой технической зоны.

```text
Create a reusable Blender vegetation kit for a contemporary temperate city in Unreal Engine: one 5 m deciduous street tree, one 2.5 m young tree, one 1.2 m shrub and one rectangular concrete planter 1.4 x 0.6 x 0.55 m. Export each asset independently at its ground pivot; keep their reference layout only in a separate catalog collection. Muted olive-green leaves with modest natural variation, realistic bark and concrete, restrained game-ready detail. Use masked leaf cards with proper alpha, two-sided leaf material, trunks with closed thickness and separate collision proxies. Include vertex color weights for later Unreal wind; leave planter rigid. Supply .blend, individual FBX and external PBR/alpha textures, no terrain, buildings, cameras, labels or gameplay logic. Target tree LOD0 under 8,000 triangles and provide simpler LODs.
```

При получении моделей сначала проверить фактические файлы и масштаб. Наличие перечисленных требований в промпте не подтверждает, что генератор их выполнил.
