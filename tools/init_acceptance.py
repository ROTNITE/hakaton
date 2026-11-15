"""Initialize the approved requirements registry without asserting unrun checks."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'B': ['Исходные хэши и dirty-состояние сохранены', 'Оригиналы/v2/бенчмарки сохранены',
          'Рабочий журнал и handoff актуальны'],
    'W': ['Плотная связная композиция города', 'Четыре границы и логичные улицы',
          'Шесть конструктивных повреждений', 'Опора и устойчивость обломков',
          'Провал без скрытой коллизии', 'Пять состояний окон', 'Читаемые интерьеры и Lumen',
          'Районы 25..150 по 10 м', 'База/доки/площадки под парк'],
    'P': ['Внешний полный цикл спасения', 'Позы/груз при hold/замене/отказе',
          'Физический подход/рампа/масса/передача', 'Торможение/встреча/перекрёсток/задний ход',
          'Взлёт/полёт/препятствие/hold/посадка', 'Парковка фургона',
          'Физические грязь/дорога/мелкая/глубокая вода', 'Фактический расход и зарядка'],
    'E': ['Восемь отдельных событий v3', 'Профиль событий v0.5.2 / 80 с',
          'Вероятности 0/100 и защита базы', 'Spread/expiry/overlap',
          'Seed независимо от политики/рендера', 'Поздняя цель без утечки',
          'Все 14 нормативных типов возмущений'],
    'H': ['Все endpoints Core 1.0', 'Полные Observation/Decision/Response/capabilities',
          'Строгий JSON и схемы', 'Idempotency/reset/close/terminal',
          'Accepted/confirmed/cancel/late results', 'Атомарные/независимые группы',
          'Непрозрачные ID/нет обязательных частных расширений', 'Часы 1 с/1-60/1-120',
          'GET не меняет состояние/RNG/сеть'],
    'A': ['Чистое ядро NSGA-II с provenance', 'Наземный A* по известной геометрии',
          'Воздушные 3D-маршруты', 'Непрерывное перепланирование от реальной позы',
          'Scout: покрытие/защита очереди/патруль', 'Rescue: назначения/занятость/ресурсы',
          'Пять стратегий и три прогноза', 'Фронты/бюджеты/seed/резервации'],
    'I': ['Global влияет на исполняемый план', 'Local каждого агента/4 решения/память',
          'Асинхронность без остановки остальных', 'Строгие проверки/устаревание/полезность',
          'OFF/MOCK/error/timeout/budget fallback', 'LIVE Global и Local подтверждены',
          'Общий реальный бюджет не выше 240', 'Нет ключей в проекте/логах/пакете'],
    'C': ['8 категорий с испытаниями', 'Space как отдельное расширение',
          '9 типов зон/геометрия/доступность', 'Пять типов работающей инфраструктуры',
          'Ограниченные ресурсы/резервы/зарядка', 'Связь/потери/задержки/mesh/разделения',
          'Пять исполнимых нормативных сценариев', 'Вычислимые игровые модели пяти сценариев',
          'Семь содержательных операций', 'Новый исполнимый синтез/FSM',
          'AST/unknown/доверие/конфликты', 'Директивы оператора и автоматические эпизоды',
          'Фиксированный и локальный реактивный baseline'],
    'U': ['Предстартовые настройки Unreal', 'Start/pause/step/stop/repeat/presets',
          'Инспектор/слои/сеть/коалиции', 'Публичный/полный взгляд',
          'Все значимые события со сквозными ID', '10 Hz/секундные снимки/substep debug',
          'Потоковая запись/сжатие/ошибки записи', 'Web-фильтры/причинная трасса/replay',
          'Графики/статистика/HV/IGD+/M1-M7', 'Экспорт JSON/CSV/TXT/архив'],
    'V': ['Свежая сборка UE и Automation', 'Blender/UE readback',
          'Python baseline и новые интеграционные тесты', 'Static delivery',
          'Три seed 480 + повтор + обычный performance', 'Legacy90',
          'Независимая протокольная совместимость', '450 последовательных native runs',
          'Максимум 150/48/40/600 в UE', '60 FPS штатной сцены/профиль тяжёлых случаев',
          'Функциональная воспроизводимость с допусками', 'Реальные кадры/видео'],
    'D': ['Одна команда запуска', 'Windows-сборка и проверка пакета',
          'Исходники/контрольные методы/зависимости', 'Записка ГОСТ19/ТЗ',
          'Эссе/приложения/формализации/протокол', 'Примеры журналов и результаты серии',
          'Происхождение ассетов/проверенный архив/ограничения'],
}


def registry():
    requirements = [{'id': f'{group}{i:02}', 'requirement': title,
                     'status': 'pending', 'evidence': []}
                    for group, titles in GROUPS.items() for i, title in enumerate(titles, 1)]
    legacy = ROOT / 'docs/quarter-v3-acceptance-matrix.md'
    for line in legacy.read_text(encoding='utf-8').splitlines():
        match = re.match(r'\| ([GEPI V]\d{2}) \| ([^|]+)\|', line)
        if match:
            requirements.append({'id': 'V3-' + match[1].strip(),
                                 'requirement': match[2].strip(), 'status': 'pending',
                                 'evidence': [], 'source': 'quarter-v3-acceptance-matrix.md'})
    return {'format': 'metarescue.acceptance.v1', 'approved_date': '2026-11-11',
            'execution_log': 'quarter-v052-execution.md', 'requirements': requirements,
            'external_tournament': {'status': 'not_verified',
                                    'note': 'Independent local references are not other teams.'}}


if __name__ == '__main__':
    target = ROOT / 'docs/quarter-v052-acceptance.json'
    if target.exists():
        raise SystemExit('Registry already exists; preserve recorded evidence.')
    target.write_text(json.dumps(registry(), ensure_ascii=False, indent=2), encoding='utf-8')
    print('Requirements:', len(registry()['requirements']))
