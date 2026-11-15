# Направление 3D-среды

2026-11-09. До создания 3D-сцены по запросу пользователя вызван встроенный **imagegen**, режим `stylized-concept`. Полученное изображение сохранено в проекте:

![Визуальная концепция спасательной операции](assets/rescue-world-concept.png)

Это **концепт**, не скриншот запущенного Unreal. После него создан отдельный физический стенд `unreal/MetaRescue/`, проверенный настоящим запуском движка; его реальные изображения и телеметрия находятся в `artifacts/unreal/`, ограничения — в `unreal/QA.md`. Художественный концепт не заменяет эти доказательства и не гарантирует одинаковую визуальную детализацию. Базовый сценарий экспортируется из пользовательского v0.3; полная динамика, планировщики и нормативный контроллер требуют отдельного адаптера.

Движок, обнаруженный локально: `C:\Program Files\Epic Games\UE_5.8`, версия 5.8.4 по `Engine/Build/Build.version`. Исходники и установка движка не включаются в проектный ZIP. Выбор runtime/API проверять по установленным заголовкам и официальной документации, а не по предположениям о старых версиях.

## Полный отправленный prompt

```text
Use case: stylized-concept. Create one production concept frame for a real Unreal Engine 5 educational search-and-rescue robot simulation, landscape 16:9. View: elevated three-quarter tactical camera, looking over a compact 90 meter by 90 meter earthquake-damaged European industrial city block, entirely 3D, physically grounded scale, high-quality real-time game environment with stylized realistic concrete forms that can be built procedurally, detailed geometry and coherent PBR materials. Intersecting asphalt streets, fractured pale concrete buildings of 2 to 4 stories, visible floor slabs, partial walls, exposed beams and scattered individual chunks of masonry, a few safety barriers and lamp posts, subtle dust and overcast late-afternoon light with warm sun highlights, ambient occlusion and soft shadows. In lower-left corner a small clean medical evacuation checkpoint, teal flat-roof modular shelter, white rescue cross, orange cone perimeter, white ambulance-like service vehicle, four rugged small orange tracked evacuation robots with flat stretcher platforms and small dark sensor towers, two distinctly recognizable blue quadcopter reconnaissance drones above the streets. Three non-graphic red rescue training mannequins visible near debris, no blood. A detached slab is visibly tilted above rubble suggesting unstable physical debris. Focus on readable navigation spaces and convincing rescue operation layout, cinematic but plausible runnable engine scene, premium architectural visualization quality, muted desaturated sage/gray concrete and charcoal asphalt, rescue orange and blue robot accents. No textual labels, no typography, no UI overlays, no futuristic holograms, no battle, no weapons, no giant robots, no dense crowds. This is visual concept art only, not evidence of implemented features.
```

Размер квартала в художественном prompt — композиционный ориентир. Он не меняет масштаб v0.2 (10 м/клетку) и не утверждает, что готова карта из этой картинки.
