# wuake

Консольная обёртка на Python над PowerShell: вводите команды, получаете их вывод.

## Запуск

В папке проекта:

```bash
python wuake.py
```

Дальше вводите команды как в PowerShell:

- `dir`
- `Get-ChildItem`
- `Get-Process | sort CPU -desc | select -first 10`

Выход:

- `exit` или `quit`
- `Ctrl+Z` затем Enter (EOF)

## Примечания

- Скрипт запускает `powershell.exe` с `-NoLogo -NoProfile` и читает/пишет через stdin/stdout (PowerShell внутри крутит цикл чтения строк).
- Если нужно использовать другой PowerShell (например, `pwsh.exe`), задайте переменную окружения:

```powershell
$env:WUAKE_POWERSHELL="pwsh.exe"
python .\wuake.py
```

## runner.py (меню сессий)

`runner.py` читает названия сессий из `sessions.json`, поднимает отдельный PowerShell-процесс на каждую сессию и даёт переключаться кликом по нижнему меню (история команд/вывода хранится отдельно для каждой сессии).

Запуск:

```powershell
python .\runner.py
```

Файл конфигурации:

- `sessions.json`:

```json
{ "sessions": [ { "name": "shell-1" }, { "name": "shell-2" } ] }
```

Управление:

- `Enter`: выполнить команду в активной сессии
- `↑/↓`: история команд активной сессии
- `Shift` + `+`: добавить сессию
- `Shift` + `-`: удалить активную сессию (если она не последняя)
- `Esc` или `q`: выход

Хоткеи лежат в `runner_settings.json` (можно поменять под себя).