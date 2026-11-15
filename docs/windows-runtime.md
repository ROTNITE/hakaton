# MetaEvolution Rescue на Windows

Распакуйте каталог целиком. Запустите `Start-MetaRescue.cmd` двойным щелчком или из терминала в этом каталоге. В поставке есть Win64-среда Unreal, Python, контроллер и локальная аналитика. На начальном экране загружается пресет района 250 м с режимом AI OFF.

Выберите «Подготовить район». После подключения контроллера миссия ждёт запуска на паузе. Кнопки позволяют начать выполнение, поставить паузу, пройти один внешний шаг в одну модельную секунду, остановить миссию и подготовить повтор. Клавиша **2** включает верхний обзор, **1** приближает базу. Сплошные ленты показывают движение, пунктир показывает оставшийся маршрут.

Требования человека-оператора вводятся через `tools/issue_operator.py` и очередь
текущего эпизода. Порядок, форматы отмены/уточнения/подтверждения, приоритеты,
ограничения и подтверждённые границы описаны в `Operator.md` поставки
(`docs/core-operator.md` в исходниках). Доставка и исполнение видны в журнале;
сообщение «queued_locally» означает только локальную постановку.

## Повтор сценария с отказом носителя

Команда ниже использует тот же приватный пресет, что и скринкаст ознакомительного комплекта. MOCK использует локальный выбор из проверенных вариантов.

```powershell
$env:METARESCUE_OUTPUT = Join-Path (Get-Location) 'output'
.\python\python.exe -B -X utf8 tools/run_mission.py --layout presets/recovery.private.json --name packaged-recovery-01 --policy nsga2_nsga2 --ai-mode MOCK --contest-coordination --capture-overview --capture-base-at 269
```

Для повтора выберите другое значение `--name`. Кадры и архивы появятся под `output`.

## Независимый запуск среды и контроллера

Из корня распакованного каталога в первом PowerShell запустите среду. Она откроет Core на 127.0.0.1:8130 и будет ждать reset.

```powershell
$env:METARESCUE_OUTPUT = Join-Path (Get-Location) 'output'
.\python\python.exe -B -X utf8 -m environment.main --layout presets/recovery.private.json --headless --exit-on-close
```

Во втором PowerShell выполните команду контроллера. Указанный режим не использует внешний API.

```powershell
$env:METARESCUE_OUTPUT = Join-Path (Get-Location) 'output'
$auditPath = Join-Path $env:METARESCUE_OUTPUT 'offline-usage.json'
.\python\python.exe -B -X utf8 -m controller.main --environment http://127.0.0.1:8130 --seed 2026 --health-port 8131 --policy nsga2_nsga2 --contest-coordination --ai-mode MOCK --ai-budget $auditPath
```

Core 1.0 описан в `Core-1.0.md`. Локальный интерфейс аналитики запускается вместе с приложением. Контрольные суммы файлов поставки указаны в `SHA256.json`. В режиме LIVE укажите общий путь журнала в `METARESCUE_LIVE_BUDGET` и настройте ключ отдельно от каталога поставки.
