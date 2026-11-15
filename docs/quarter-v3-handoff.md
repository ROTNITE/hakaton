# Передача RescueQuarter v3 в новый чат

Это промпт и проверенный срез незавершённой работы для следующего исполнителя.
Передача подготовлена 2026-11-11. Файлы проекта и реальное состояние компьютера
имеют приоритет над этим срезом. Не перезапускай работу с нуля и не объявляй
выполненным то, что ниже отмечено открытым или только подготовленным.

## Поручение пользователя

Продолжи реализацию утверждённого плана RescueQuarter до полного завершения.
Нужен правдоподобный плотный разрушенный город в сдержанном реалистичном стиле,
все восемь событий бенчмарка v0.3 с визуальным и физическим влиянием, безопасное
исполнение движения и интерфейсы будущего контроллера. Особенно тщательно
проработай визуал каждого сценария. Пользователь явно разрешил субагентов и
попросил распараллелить независимые участки. Не ограничивай задачу уже зелёными
проверками. Получать повторное согласование утверждённого плана не требуется.

Рабочая папка: `C:\Users\rotn1\Documents\ChatGPT\metaroy`, Windows, PowerShell.
Пользователь предпочитает русский язык, самостоятельную работу, реальные
кадры/прогоны и честную границу между сделанным и непроверенным.

Исходный полный утверждённый план ОБЯЗАТЕЛЬНО прочитать:
`C:\Users\rotn1\.codex\attachments\43feacee-3d80-442d-9fde-6565d50999dc\pasted-text-1.txt`.
Если вложение недоступно, требования ниже сохраняют основной объём; сначала
поищи его в доступных материалах и не теряй перечисленные критерии.

Исходные референсы пользователя: дневной город после землетрясения с целыми и
разрушенными домами, крупными плитами, кирпичной осыпью, разломанной дорогой,
инженерными коммуникациями, дымом/огнём/грязной водой и безопасной базой.
Исходные снимки нынешней сцены и кадры «до» находятся в baseline и старой v2.
Не превращать результат в мультяшную диораму или пустой полигон.

## Обязательное чтение до изменений

1. `AGENTS.md` — единственный общий файл инструкций; прочитай текущую версию.
2. `docs/current-concept.md`, `docs/benchmark-v0.3-spec.md`,
   `docs/benchmark-v0.3-review.md`, `docs/benchmark-research-plan.md`.
3. `docs/stage-1-interaction.md`, `docs/stage-1-review.md`, `contracts/`.
4. `unreal/README.md`, `unreal/QA.md`, `docs/3d-visual-direction.md`,
   `docs/3d-world-status.md`, `docs/3d-asset-library-review.md`.
5. `docs/quarter-v3-execution-plan.md`, `docs/quarter-v3-integration.md`,
   `docs/quarter-v3-progress.md`, `docs/quarter-v3-acceptance-matrix.md`.
6. Реальные исходники `unreal/MetaRescue/Source/MetaRescue/`, генераторы и
   проверки `unreal/tools/`, сценарий `Content/Scenario/quarter.json`, библиотеки
   `library-v2.json` и `library-v3.json`.

Документы progress/matrix/integration отражают промежуточные ревизии и местами
отстают от последних успешных прогонов. Проверяй их утверждения по логам и
архивам, а затем обнови. Не используй старую запись «всё готово» как приёмку.

## Не нарушать

- A*, NSGA-II, поиск объезда и объединение с работой другого разработчика НЕ
  входят в этап. При препятствии — остановка с причиной и ожидание команды.
- Полная гидродинамика, плавучесть, тушение и расчистка роботами не требуются.
- Нормативный Core Protocol 1.0/документ1.1 не менять. Новый HTTP-сервер не нужен.
- Пользовательские `benchmarks/metarescue-v0.3/` (16 исходных файлов) и v0.2
  сохранены без правок. `benchmark/` — другой ранний черновик, не подмена v0.3.
- Сохранять оригинальные модели/архивы/хэши и prepared/v2. Новая геометрия и
  материалы делаются производными скриптами. Генерируемые blend/FBX/uasset/umap
  вручную не редактировать; править генераторы и пересоздавать явно.
- Почти весь проект untracked, есть старые пользовательские удаления World,
  Starter.py/main.py и др. НЕ reset/clean/revert и НЕ восстанавливать удалённый
  Evolution World. Не проводить несвязанный рефакторинг. Публикация не заказана.
- Не создавать второй общий AGENTS/agent.md. Не перезаписывать доказательства.
- Один владелец UBT/Unreal/импортов/сохранения карты: никогда два UE одновременно.
  Они используют общий Saved, а Windows блокирует DLL/uasset. Нельзя изменять
  C++/headers во время сборки. На native-прогоны замораживать ВСЕ исходники,
  tools/config/scenario/map/DLL: runner сверяет их SHA256/mtime/size до и после.
- Пользователь разрешил самостоятельно закрывать оставшийся редактор. Сначала
  проверяй реальный процесс и несохранённые правки; не убивай чужие процессы.
- До каждого нового native сохранять свежие кадры/телеметрию отдельно. Runner
  делает это в уникальную папку и отказывается перезаписывать существующую.

## Среда и команды

- UE5.8.4: `C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/`.
- Проект: `unreal/MetaRescue/MetaRescue.uproject`, карта `/Game/Maps/RescueQuarter`.
- Blender: `.tools/blender/blender-4.5.15-windows-x64/blender.exe`.
- C++ Visual Studio toolchain/WindowsSDK установлен; Python stdlib, ffmpeg есть.
- Компьютер по native-логам: i9-12900KF, NVIDIA RTX3080, Windows11.

```powershell
python -B -X utf8 unreal/launch.py --quarter --build
python -B -X utf8 unreal/launch.py --quarter --editor
python -B -X utf8 unreal/tools/run_quarter_validation.py traffic --prefix NEW
python -B -X utf8 unreal/tools/run_quarter_validation.py static --prefix NEW
python -B -X utf8 unreal/tools/run_quarter_validation.py effects --prefix NEW --fixed-step-fps 30
python -B -X utf8 unreal/tools/run_quarter_validation.py zero --prefix NEW --fixed-step-fps 30
python -B -X utf8 unreal/tools/run_quarter_validation.py replay --prefix NEW --fixed-step-fps 30
python -B -X utf8 unreal/tools/run_quarter_validation.py random --prefix NEW
python -B -X utf8 unreal/tools/run_quarter_validation.py showcase --prefix NEW
python -B -X utf8 -m unittest discover -s unreal/tools/tests -v
python -B -X utf8 -m unittest discover -s "benchmarks/metarescue-v0.3/main part/tests" -v
python -B -X utf8 -m unittest discover -s tests -v
git diff --check
```

Runner: traffic100с каждый, static270с, effects180с каждый, random480с каждый
seed20261109/20261110/20261111, showcase240с с записью PNG5fps на28..148с.
`--case` выбирает один fixture/эффект/seed; `--seconds` — диагностика30..900с.
`windows` — отдельный статический осмотр с external-control. Все prefix новые.

UE Automation: запускать UnrealEditor-Cmd.exe с проектом, `-NullRHI -unattended
-NoSound -nosplash`, `-ExecCmds="Automation RunTests MetaRescue"`,
`-TestExit="Automation Test Queue Empty"`, `-ReportExportPath=<уникальный путь>`.
Редакторские скрипты: `-run=pythonscript -script=<абсолютный путь>`; не запускать
NullRHI для визуальной приёмки. Обычный запуск ничего не пересоздаёт.

## Уже реализовано

### Геометрия и библиотека

- Базовое состояние/исходники/хэши/кадры сохранены `artifacts/quarter-v3/baseline/`.
- Проверены26 исходных комплектов. `blender/prepared/v3/`: GlazingKit15 окон
  (3 размера × clean/dirty/cracked/broken/empty), SceneryKit11 модулей (осколки,
  3 меблированные комнаты, скамья, контейнеры, вентиляция), BuildingVariants2
  текстурированные руины, включая реально срезанную низкую.
- Исправлена реальная ошибка origin объединённых модулей: матрица запекается
  в геометрию до экспорта. Добавлены ножки мебели/колёса контейнеров.
- Плотнее кварталы, дворы и фон; шесть вариантов повреждений, рваная кромка
  исходного провала с точной статической треугольной коллизией и грунтом,
  настоящая пустота дорожного коллайдера, труба и обломки внизу.
- Реальные min-vertex grounding и четыре геометрические опоры наклонных плит;
  поддерживаемая обрушиваемая секция вместо висящих демонстрационных плит.
- Часть повторов объединена HISM, но поверхности помещений/окон/стен исключены
  из HISM для Lumen. Это НЕ решило окончательно чёрные комнаты.
- Новый материал ThinTranslucent+SurfaceForwardShading, реальное отсутствие
  стекла в разбитых окнах и оставшиеся осколки, crack/dirt masks/roughness/normal.
- Исправлена ошибка stale-cache материалов: build_quarter_v3.py теперь учитывает
  содержимое исходного uasset. Opacity стекла .018 clean/.07 загрязнённое — слой
  поверх пропускающего стекла, а не1, блокировавший трансмиссию.
- Материалы копируются в MaterialsV3/Instances; originals/v2 сохраняются.

### События и последствия

- MRDistrictSettings.h — общий блок вероятностей12/12/10/14/14/15/12/20%, seed,
  горизонт480с, окно30с. MREnvironment.h/.cpp не зависит от Actor/Chaos/рендера.
- Восемь типов: collapse/fire/flood/mud/road_damage/smoke/low_visibility/new_target.
  Воспроизводимая лента FRandomStream, независимая от движения; семантика v0.3,
  НЕ побитовый PythonMT19937. До2 окон распространения fire/flood .72/.65.
- Статическая защита базы, подходящие каталоги мест, rejected attempts,
  static/random/showcase; старые обязательные таймеры отключены в новом режиме.
- Mud cost2.25, road1.9, water2.0; вода .8см/с до42, проезд запрещён>25см.
  WaterDepth согласована с полуметровой маской реального низкого основания,
  фасады исключены, есть пена/мокрые края. Нужна настоящая визуальная приёмка.
- Smoke .52×90с, fire-smoke70с, fog .62×100с; перекрытие перемножается. Ревизия
  меняется при событиях, окончании видимости и изменении уровня воды.
- Семь Niagara systems: BuildingFire,HeavySmoke,CollapseDust,LowVisibility,
  Sparks,PipeLeak,WheelSplash. Есть bounds, fade, отдельные материалы и брызги
  от реального движения. Нужен осмотр каждого эффекта, не только existence.
- Late target скрыта до события и неизвестна контроллеру до наблюдения.
  public-frames.jsonl сохраняет историю, приватная лента в environment-truth.json.
- `--visual-probe events` снимает реальные источники событий после2/12/60с;
  обычный photo-tour не должен конкурировать с этим режимом.

### Исполнение и API

- Движение силами/моментами, лучевая опора, масса240/320кг, механизмы рампы,
  колёс/гусениц/роторов и реальная посадка сохранены. Коллизии не выключаются.
- Исправлены нестабильное взаимное уступание, отсутствие тормоза при мгновенно
  разгруженных пружинах, выезд задним ходом, взлёт/посадка и полные габариты.
- Прогноз конечный, не экстраполирует за финиш; отдельное достижение высоты.
  Мягкий запас вокруг соседнего дока можно покинуть только удаляясь от соседа
  при уже разделённых физических оболочках. Нельзя подъезжать через него.
- AccountExecutedMovement синхронизирует post-physics позу/дистанцию/энергию.
  Проверка не ослаблена увеличением допуска.
- Внутренние Blueprint API MRWorld: SubmitRouteMeters, HoldAgent,
  QuerySurfaceMeters, PublicObservationJson. Метры API↔сантиметрыUE×100,
  XYZ какUE, Zвверх. CommandId idempotent/stale-safe; до128 команд на агента,
  до4096 точек. Hold/замена не телепортируют и не сбрасывают груз.
- Demo dispatcher отключается `--external-control`; private truth/geometry
  не выдаются в public-observation. Детали — quarter-v3-integration.md.

## Реально проверено к передаче

Не смешивать ревизии: следующие семь fixture прошли в процессе доработки, а
после финальных изменений их надо повторить на одной окончательной ревизии.

`artifacts/quarter-v3/runs/`:

- team03-traffic-following:100с PASSED, оба финиша,0контактов.
- team03-traffic-crossing:100с PASSED, оба финиша,0контактов.
- team04-traffic-reverse:100с PASSED, выезд и финиш,0контактов.
- team04-traffic-flight:100с PASSED,3дрона с пересечением на одной высоте,0контактов.
- team04-traffic-landing:100с PASSED, посадка, rotors0,0контактов.
- team04-traffic-meeting:100с PASSED, встречный проезд,0контактов.
- team04-traffic-obstacle_replace:100с PASSED, остановка перед барьером, новая
  команда, финиш, cargo/mass320 сохранены, stale replay/conflict/noTeleport
  проверены реальными вызовамиAPI;0контактов.

После прогрева эти реальные1600×1000прогоны давали около140–144FPS,p95≈8мс,
RAM≈3.3ГБ. Это не проверка тяжёлых сочетаний всех эффектов и не финальный FPS.

UE Automation unit-team03 и unit-team04:5 succeeded,0 failed (4среды+1Safety
FiniteRoutePrediction с несколькими проверками). Последняя сборка
build-team05-scorch.log успешна. После неё изменён только checker округления,
нового native-прогона ещё НЕ было.

Python v0.3:30/30, контракты15/15 — acceptance-v03-tests.log и
acceptance-contract-tests.log. Инструменты:10/10 в
acceptance-tool-tests-clock-rounding.log. AST/gitdiffcheck выполнялись.

Blender: blender-verification.json (оригинальные26хэшей),
slab-contact-inspection.json (15положений,4контакта,COMвопорномконтуре),
scenery-module-datum-inspection.json (7объединённыхмодулей наZ0).
Это статическая геометрическая проверка, не испытание нагрузки Chaos.

Legacy RescueDistrict.umap SHA256 сейчас совпадает с исходным:
4336ACEB0AFD4B5BDE8C77D2F55FEE9342537FCBAF9DE8E2E5C8D0FBC39C743A.
Настоящая legacy90 regression после всех изменений ещё обязательна.

## Последняя точка остановки — начать отсюда

Последний native `team05-fixed30-zero`:
160.000008 модельных секунд, восемь вероятностей0, пустая лента,0контактов,
common smoke passed. Worldwall≈35.52с; он НЕ пройден официально: verifier
сравнивал requested_fixed_fps точным ==, а Unreal парситFPS float и даёт
29.999998435 вместо30, delta0.0333333350718.

Это уже исправлено в текущем check_clock_profile:
`close(final['requested_fixed_fps'], request..., .00001)`.
Тесты проверяют допустимое округление и отклоняют реально неправильную частоту;
10/10 зелёные. Не вноси то же исправление второй раз. Сначала перечитай файл.
Не переписывай старый failed архив как successful; запусти свежий prefix.
Из-за остановки цепочки восемь отдельных effects ещё НЕ запускались.

Следующий быстрый цикл:
1. Проверить нетживогоUE/сборки, source status и актуальный checker.
2. `zero --prefix team06 --fixed-step-fps30` (написать с пробелом вCLI),160с.
3. `effects --prefix team06 --fixed-step-fps30`,8×180модельныхс, каждый эффект
   со100% и остальными0. Осматривать свежиеeventPNG, lifecycle, клетки/глубину,
   actualFXalive/hidden, скрытые цели. Исправлять корни обнаруженных дефектов.

Fixedfunctional разрешён толькоявно: `--fixed-step-fps 30` ->
`-UseFixedTimeStep -FPS=30`. Это реальныеUEтика/Chaos/render, но другой шаг
контроллеров. Не применять кtraffic/static/showcase/windows/capture и не
называть модельные30FPS производительностью. Metadata time_step_mode,
requested_fixed_fps,model_delta_s_min/max,wall_elapsed_s,render_wall_fps;
verifier fixed выводит fps/p95/target60=null. План принят:3×480functional+
ещё один480вобычномвремени для тяжёлой производительности. Ни один из них
пока не выполнен. Replay отдельный одинаковыйseed с сравнениемлент.

## Остаток — нельзя потерять

1. Окна/интерьеры всё ещё слишком чёрные. Нормальный новый рендер видит
   трансмиссию/осколки/мебель, но непрямой свет не принят. Реальные diagnostics
   `diagnostics/lumen-cache-01` (r.Lumen.Visualize5) и lumen-scene-01 (3)
   показывают округлые закрывающие SDF вместо прямоугольных проёмов, pink/yellow
   surface-cache проблемные области. Причина не доказана окончательно.
   GIQuality3/Lumenenabled подтверждены. Нельзя просто осветить fakePointLight.
2. Готов НЕИСПОЛНЕННЫЙ кандидат `artifacts/quarter-v3/prepare_lighting_candidate.py`:
   производные клоны GlazingKit/UrbanKitwalls с DF3/cards24 и перестроением
   после назначения правильных материалов; режим -MRLightingBakeScene запекает
   anisotropic scale всех InteriorLightingSurface Cube в собственные меши,
   возвращаетscale1, сохраняетcollision/bounds/transform. Не меняетEngineCube
   и v2. ВыполнениеAPI/readbackещёнепроверено. СначалаbaselineDF иEVсравнение.
   Возможныепричины:lowres/staleDF стекла и масштабированиеCube9×9×.16.
   Камера уже поддерживает диагностический -MRDiagnosticEV=9/11/12.8.
   Команда дляDF: -ExecCmds="r.Lumen.Visualize 0,ShowFlag.VisualizeMeshDistanceFields 1".
   При продвижениикандидатавtools сохранитьпорядок libraryimport→lightingclones→
   build_quarter_v3→bakeScene→readback→native. В MRDistrictInstances уже есть
   фильтр SM_wall_/SM_window_ независимо папки. verify_quarter_v3 уже узнаёт
   окна поmanifest и проверяет реальныеgraphopacity/transmission/style/UV;
   сам новый строгийreadbackещё НЕ исполнен.
3. Улучшить/принять визуал каждого из8событий: огоньслои/дым/угли/копоть,
   обвалпыль/новыепрепятствия, водаисточник/рябь/рост/мокрыйкрай/пенабезстен,
   грязьколеи/лужи/брызги, дорожныефрагменты/трещины/просадка, локальныедым/
   пыльнаязавеса срастворением, поздняяцельраскрытие/обнаружениебезутечки.
4. Настоящий static270 сдоставкой. Раннийstatic130/zero160 доставкунепоказал;
   возможныостановкинаавторскихмаршрутах. Не убратьgate,неотключатьcollision,
   ненеявныйобъезд; исправитьгеометрию/заданныймаршрут/исполнениекакположено.
5. Триseed480, повтородногоseed,0/100%,spread,expiry,overlap; обычныйrandom480
   дляперфоманса, финальныеtrafficсемь и дополнительныепроверки:
   дронпередзданием/вертикальноеобъектноеудержание,hold/resume,парковкаvan.
6. Физическаяпроверкаcost/speed/energy/шallow/deepwater: покаqueriesнедостаточно.
   `artifacts/quarter-v3/surface-probe-design.md` — проект четырёх существующих
   роверовнаразныхулицах, реальныеполосыпослеt30, shallowпереезд/deepstop,
   частаяреальнаятелеметрия. ЭтоНЕреализовано.
7. Старый --mechanics-probe рекламируется, но старое спавнениепробников удалено;
   check_environment_probes ждётIDs100/101/фиксированныепятнаv2. Нельзявыдать
   новыепустыеполяилиформулыкакстаруюприёмку. Явномигрировать/заменитьпроверку.
8. Кандидаты ещё НЕ применены: safety-extra-fixtures.patch и
   safety-extra-fixtures-design.md (air_obstacle,hold_resume,van_conflict).
   Van требует дополнительнойточнойтелеметрии/учётаконтактовWorld-ownedчастей.
9. Проверить6разныхконструктивныхсилуэтовнепометкам: collapsedfloorvariant
   можноусилитьреальнымисложеннымиподдерживаемымиплитами; границы4сторон,
   назначениепространств, отсутствиеповисшихобломков, пропсыпроходы/база.
10. Реальныекадры«до/после», видеозаписьэффектов(PNG→ffmpeg), телеметрия,
    настройки,интеграционныйгайд. Видео пока НЕ создано.
11. ФинальныеUE/Blender/importreadback/30+15tests/RescueDistrict90,
    хэшиoriginals+v2,дифф,актуальныеREADME/QA/status/AGENTS/матрицаприёмки.
    Отчётпопродуктовымрискам,ограничениям,отклонениям5м3D vs10м2D.

## Состояние на момент передачи

По последней проверке живых UnrealEditor/Blender нет; перед стартом перепроверь.
Последняя цепочка terminal, не продолжай ждать старый handle. Не трогать
несвязанные Python-процессы benchmark/Jupyter/watch-skill.

Goal старого чата инструмент возвращает usageLimited, неcomplete. Пользователь
просилgoalиавтономнуюработу. В новом чате заведи отдельную goal для полного
исходногообъёма, если нетактивной; не отмечатьвыполненнойдоrequirement-by-
requirementаудита. Этотлимитневылечитьupdate_goal(active): такойоперациинет.

Субагентыстарогочата могутбытьнедоступны/лимитированы; создайновыхпринеобходимости.
Удобное разделение: safety MRAgent*/MRTrafficProbe; scene MRDistrict/Camera/
Blendergenerator; acceptance Pythonchecks/матрица; основнойагентсобытия/вода/
материалы и эксклюзивныеUEпроцессы. Не редактироватьодинфайлвдвоём.

Не требуй заново одобрить исходныйплан. Сначала прочитай всёперечисленное,
коротко сообщи проверенноетекущеесостояние и продолжи ближайший реальный шаг.
Цель — весь результат пользователя, а не количество кода или число зелёных
частичных отчётов. Любую ошибку сохраняй и исправляй, не ослабляя проверки.
