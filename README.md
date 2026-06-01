# AOCapp

Настольное приложение на PySide6 для расчёта и визуализации сверхпроводящей интегральной структуры: микрополосковые линии, трансформаторы импеданса, SIS-переход, radial stub, DC-block и S21-отклик.

## Возможности

- Группированный ввод параметров структуры через UI.
- SVG-preview геометрии с масштабированием и панорамированием.
- Расчёт S21 по тем же параметрам, которые используются для preview.
- График S21 vs Frequency и текстовый лог расчёта.
- Сохранение результата S21 в `.tab` файл.
- Версификация приложения через `aocapp/application/version.py` и GitHub-теги.

## Запуск из исходников

В проекте уже используется локальное окружение `.venv`.

```bash
.venv/bin/python -m aocapp
```

Если окружение нужно пересоздать:

```bash
python3.11 -m venv .venv
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install -r requirements.txt
```

## Локальная сборка

Сборка делается через PyInstaller, как в `RnSApp`.

macOS/Linux:

```bash
bash ./build.sh
```

Windows:

```bat
build.bat
```

Результат появляется в `dist/SMC_app`. Иконка приложения лежит в `assets/aocapp-icon.png` и `assets/aocapp-icon.ico`.

## Релиз и версии

Версия хранится в `aocapp/application/version.py`:

```python
__version__ = "0.1.0-dev"
REPO_SLUG = "atepart/SMC_app"
```

Релизный скрипт обновляет версию, создаёт commit, аннотированный tag и отправляет изменения в GitHub.

macOS/Linux:

```bash
./release.sh -t v0.1.0
```

Windows:

```bat
release.bat v0.1.0
```

После push тега GitHub Actions собирает архивы для Windows и macOS и публикует их в GitHub Release.

## GitHub Actions

Workflow находится в `.github/workflows/build.yml`.

Он запускается:

- при push любого тега;
- вручную через `workflow_dispatch`.

Матрица сборки повторяет подход `RnSApp`:

- Windows 2022: `x86`, `x64`;
- macOS latest: `arm64`;
- macOS Intel: `x64`.

## Структура проекта

- `aocapp/main.py` - composition root приложения.
- `aocapp/ui/` - PySide6 UI, SVG preview, график S21.
- `aocapp/application/` - use cases и версия приложения.
- `aocapp/domain/` - модели и параметры расчёта.
- `aocapp/infrastructure/` - геометрия, S21-калькулятор, SVG-renderer.
- `aocapp/api/` - адаптеры к расчётному backend-коду.
- `backend/` - исходные расчётные модули и старые примеры.

## Примечания

- `.tab`, `build/`, `dist/`, `*.spec` и временные файлы игнорируются git.
- Для локальной сборки можно переопределить интерпретатор переменной `PYTHON_BIN`, например `PYTHON_BIN=.venv/bin/python bash ./build.sh`.
