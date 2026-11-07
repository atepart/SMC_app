# smcapp

Настольное приложение на PySide6 для расчёта и визуализации сверхпроводящей интегральной структуры: микрополосковые линии, трансформаторы импеданса, SIS-переход, radial stub, DC-block и S21-отклик.

## Возможности

- Группированный ввод параметров структуры через UI.
- SVG-preview геометрии с масштабированием и панорамированием.
- Расчёт S21 по тем же параметрам, которые используются для preview.
- График S21 vs Frequency и текстовый лог расчёта.
- Последний успешный расчёт серым за текущей синей кривой; редактируемый красный порог Y line (−5 dB по умолчанию).
- Сохранение результата S21 в `.tab` файл.
- Сохранение параметров в `.smcdesign` или `.json`; чтение старых `.aocdesign` и `.aocapp`.
- Версификация приложения через `smcapp/application/version.py` и GitHub-теги.

## Запуск из исходников

Проект и его зависимости управляются через `uv`.

```bash
rtk uv sync
rtk uv run python -m smcapp
```

Пакет переименован из `aocapp` в `smcapp`: после обновления исходников выполните `rtk uv sync`.
Настройки темы, панелей и каталогов из AOCapp переносятся при первом запуске, не заменяя уже заданные настройки smcapp.

## Файлы параметров

`.smcdesign` — обычный UTF-8 JSON с полями `format: "SMCapp Design"`, `version: 1` и объектом `parameters`.
Состав параметров и их backend-единицы не изменились. Можно сохранять тот же документ с расширением `.json`.
Старый маркер `AOCapp Design` принимается без конвертации из `.aocdesign`, `.aocapp` и `.json`.
При повторном сохранении записывается новый маркер; диалог предлагает `.smcdesign`.
Чужой JSON, неизвестная версия и некорректные параметры отклоняются.

Файл содержит входные параметры, а не рассчитанную кривую: после открытия нажмите `Run S21`.
Результат S21 сохраняется отдельно в `.tab`, изображение графика — в `.png`.
Чтобы сохранить совместимость с существующими установками и обновлениями, имя сборки `SMC_app`,
каталог результатов `Documents/SMC_app` и адрес GitHub-репозитория остаются прежними.

Тесты и проверки:

```bash
rtk uv run ruff check .
rtk uv run black --check .
rtk uv run isort --check-only .
rtk uv run pytest
```

## Локальная сборка

Сборка делается через PyInstaller, как в `RnSApp`.

macOS/Linux:

```bash
rtk uv run pyinstaller smcapp/__main__.py -n SMC_app --onedir --icon=assets/smc-logo.ico --noconsole --windowed -y --add-data="assets:assets"
```

Windows:

```bat
rtk build.bat
```

Результат появляется в `dist/SMC_app`. Иконка приложения лежит в `assets/smc-logo.png` и `assets/smc-logo.ico`.

## Релиз и версии

Версия хранится в `smcapp/application/version.py`:

```python
__version__ = "0.1.0-dev"
REPO_SLUG = "atepart/SMC_app"
```

Релизный скрипт обновляет версию, создаёт commit, аннотированный tag и отправляет изменения в GitHub.

macOS/Linux:

```bash
rtk ./release.sh -t v0.1.0
```

Windows:

```bat
rtk release.bat v0.1.0
```

После push тега GitHub Actions собирает архив для Windows x64 и публикует его в GitHub Release.

## GitHub Actions

Workflow находится в `.github/workflows/build.yml`.

Он запускается:

- при push любого тега;
- вручную через `workflow_dispatch`.

Релиз собирается только для Windows 2022, архитектура `x64`.

## Структура проекта

- `smcapp/main.py` - composition root приложения.
- `smcapp/ui/` - PySide6 UI, SVG preview, график S21.
- `smcapp/application/` - use cases и версия приложения.
- `smcapp/domain/` - модели и параметры расчёта.
- `smcapp/infrastructure/` - геометрия, S21-калькулятор, SVG-renderer.
- `smcapp/api/` - адаптеры к расчётному backend-коду.
- `backend/` - исходные расчётные модули и старые примеры.

## Примечания

- `.tab`, `build/`, `dist/`, `*.spec` и временные файлы игнорируются git.
- Все Python-команды разработки и сборки запускаются через `uv`; подробные правила находятся в `AGENTS.md`.
