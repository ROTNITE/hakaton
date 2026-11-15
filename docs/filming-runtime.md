# Съёмка MetaEvolution Rescue

Отдельный opt-in режим наблюдателя для Unreal Engine 5.8. Он создаёт камеру,
плавно проходит заданные ключи и записывает нативные кадры без HUD. Камера
может следовать за настоящим агентом, ждать времени миссии или подтверждённой
средой доставки. Контроллер не получает истинное состояние через камеру.

Без `-MRFilmPlan` подсистема не создаётся. Исходные карты не переиздаются.
Съёмочный runtime содержит собственные копии Source, Config и Content.
Подготовка проверяет хэши и набор файлов, сборка/запись используют общий
`D:/MetaRescue-output/locks/unreal-owner.lock` и отказываются запускаться при
другом Unreal. Новые результаты требуют нового каталога; существующие не
перезаписываются. Пользовательские импорты и бенчмарки не изменяются.

## Инструменты

- `unreal/MetaRescue/Source/MetaRescue/MRFilmSubsystem.*` — камера, нативная
  последовательность PNG и журнал каждого кадра.
- `tools/filming/film_capture.py` — снимок runtime, сборка и демонстрационная
  запись; также проверяет каждый PNG полным декодированием и сверяет кадры.
- `tools/filming/film_core_take.py` — тонкий адаптер существующего
  `tools/run_mission.py`: меняет путь съёмочного проекта, разрешение и флаги
  камеры. Core/контроллер/мир/архивы исполняются штатным runner.
- `tools/filming/author_film_plans.py` — воспроизводимые планы ролика.
- `tools/filming/compose_film.py` — монтаж, титры, цвет, H.264/AAC и собственный
  синтезированный музыкальный трек; исходные кадры остаются неизменными.

Основные Python-зависимости проекта сохраняются. Дополнительные библиотеки
съёмочного инструментария перечислены в `tools/filming/requirements.txt`:
Pillow для проверки PNG/титров и NumPy для синтеза звука. В данной работе они
уже были установлены; новых библиотек не устанавливалось. Нужны FFmpeg/FFprobe
в PATH, а для сборки — существующие UE/C++ toolchain проекта.

## Повторение

Из корня репозитория, при свободном Unreal. Для каждого нового запуска
менять имена runtime, take, миссии и монтажа.

```powershell
python -B -X utf8 tools/filming/author_film_plans.py D:/MetaRescue-output/filming/new-film/plans
python -B -X utf8 tools/filming/film_capture.py --repo . --runtime D:/MetaRescue-output/filming/new-film/runtime/MetaRescue --prepare --build
python -B -X utf8 tools/filming/film_capture.py --repo . --runtime D:/MetaRescue-output/filming/new-film/runtime/MetaRescue --plan D:/MetaRescue-output/filming/new-film/plans/environment-plan.json --take D:/MetaRescue-output/filming/new-film/takes/environment
python -B -X utf8 tools/filming/film_core_take.py --repo . --runtime D:/MetaRescue-output/filming/new-film/runtime/MetaRescue --layout D:/MetaRescue-output/missions/standalone-22-precise-recovery/world.private.json --plan D:/MetaRescue-output/filming/new-film/plans/core-plan.json --take D:/MetaRescue-output/filming/new-film/takes/core --name new-film-core
python -B -X utf8 tools/filming/compose_film.py D:/MetaRescue-output/filming/new-film/edit.json D:/MetaRescue-output/filming/new-film/final
python -B -X utf8 -m unittest discover -s tools/filming/tests -v
```

Формат монтажного JSON и примеры находятся в `tools/filming/README-edit.md`.
Пути кадров в нём должны ссылаться на новые take. Готовый монтажный лист
данного ролика хранится рядом с его результатом и исходными записями.

## План камеры

Формат `metarescue.film.v1`, `fps: 30`, `warmup_frames: 120`, список `shots`.
План содержит переносимый уникальный `id`, целое `frames`, необязательное
`wait_frames` и минимум два ключа `keys`. У ключа: `u` от 0 до 1,
`eye_cm`, `look_cm`, `fov` 15..100. Концы должны покрывать 0 и 1.
Положение/направление/FOV интерполируются плавной кривой с замедлением
на концах. Все координаты — сантиметры Unreal.

`follow` задаёт точный ID существующего агента; в этом случае координаты
ключа являются смещениями от его измеренной позы в 3D. `follow_space` —
`world` либо `heading`. `collision_test` включает защитную сферическую
трассу камеры. `wait_until_s` ждёт настоящего времени Core, а в legacy —
времени мира. `wait_for_delivered` ждёт фактического счётчика среды.

Legacy записывается при фиксированных 30 шагах/с. Core сам владеет
переменным физическим квантом до 1/60 с; камера выбирает реальные кадры
примерно с частотой 30 в секунду времени рендера, не меняя часы Core.
Это запись для презентации, не замер FPS или приёмка производительности.

## Пауза, точность и происхождение

Внутри активной Core-миссии запись идёт по исполняемым физическим кадрам;
между внешними шагами пустые кадры не добавляются. Только явно заданный
заключительный план с `wait_for_delivered` может снимать уже остановленную
сцену. В таких строках `held_tail: true`, время Core остаётся прежним, а
`capture_time_s` продолжает время ролика. Физика ради записи не возобновляется.
Последний краткий план завершает принадлежащий съёмке native-процесс;
штатный mission runner по-прежнему требует проверенные архивы и exit 0.

`frames.jsonl` связывает PNG с кадром/планом, камерой, временем мира/Core,
реальными позами, состояниями и грузом агентов, счётчиками среды. Факты
снимаются в callback обработки скриншота после post-actor шага Core, чтобы
погрузка/передача на текущем кадре не отставала на один квант. Журнал
наблюдателя не передаётся контроллеру и не заменяет нативные Core-журналы.

`capture.json` обозначает только законченную последовательность изображений.
Для Core отдельно обязательны `mission-manifest.json`, проверка нативного
архива и `verification.json`. Постановочная legacy-среда и настоящая Core-миссия
имеют отдельные take и отдельные пометки в ролике. Огонь/обвал/вода в showcase
имеют намеренно заданную ленту; это не случайный конкурсный прогон.

Результаты конкретной съёмки, ограничения, источники и выполненные проверки
сохраняются в отдельном каталоге `D:/MetaRescue-output/filming/`.
