# twylt-pack-essential 0.2.0

Шесть инструментов TWYLT для ToolHub: `echo`, `sleep`, `wget`, `curl`, `ping`, `web_search`.

## Установка

Python 3.10+. Из каталога распакованного пакета:

```bash
uv venv
uv pip install ../twylt-1.1.0 .
```

Или `python -m venv .venv`, затем установка через Python этого окружения: `.venv/bin/python -m pip install ../twylt-1.1.0 .` (Windows: `.venv\Scripts\python.exe`).

Для ICMP `ping` в Linux нужен системный пакет `iputils-ping`:

```bash
sudo apt-get install iputils-ping
```

HTTP-инструменты используют стандартную библиотеку Python: системные wget и curl не нужны. Это структурированные HTTP(S)-инструменты с одноимёнными командами, а не полные обёртки всех флагов GNU wget/libcurl. `ping` поддерживает Linux и Windows; macOS пока не поддерживается.

## Настройка окружения

```bash
export TWYLT_GUARDRAILS=1
export TWYLT_WORKSPACE_ROOT=/absolute/path/to/workspace
export TWYLT_SEARXNG_URL=http://searxng:8080
```

Каталог workspace должен уже существовать. Пути `out.txt` и `/out.txt` относятся к корню workspace, а не к корню ФС хоста. Родительские каталоги назначения должны существовать; `..`, симлинки, hardlinks и переходы на другие mount points запрещены. Общая политика реализована в TWYLT 1.1.0 и применяется при TWYLT_GUARDRAILS=1. Опционально `TWYLT_INCIDENT_LOG` задаёт абсолютный путь журнала вне workspace; иначе события отказа идут в stderr. Это проверка путей, не изоляция от параллельной подмены файлов другим процессом.

`TWYLT_GUARDRAILS=1 TWYLT_DISABLE_NETWORK=1` запрещает `wget`, `curl`, `ping`, `web_search`, оставляя `sleep` и `echo` рабочими. HTTP-инструменты используют системную проверку TLS и стандартные переменные proxy окружения Python (`http_proxy`, `https_proxy`, `no_proxy`).

## Запуск и ToolHub

Из корня пакета:

```bash
.venv/bin/python tools/sleep/run.py '{"seconds":1.5}'
printf '%s' '{"url":"https://example.com/"}' | .venv/bin/python tools/curl/run.py
.venv/bin/python tools/curl/run.py '{"describe":"json_spec"}'
INPUT_DESCRIBE=requirements .venv/bin/python tools/curl/run.py
```

Поддерживаются все режимы TWYLT: `brief`, `schema`, `few_shots`, `requirements`, `json_spec`, а также `--help`, `--version`, `-v`. При передаче JSON через аргумент/stdin результат идёт в stdout. Без них используется стандартный транспорт `input.json`/`output.json`; cwd может находиться внутри workspace или внутри отдельного TWYLT_ALLOWED_CWD, включая подкаталоги. Разрешение cwd относится только к транспорту.

Для toolpack-builder сканируйте **только `tools/`**. Каждый `tools/<name>/tool.py` содержит свой контракт и собственную реализацию, импортируя только нужный общий модуль; соседний `run.py` — штатный загрузчик TWYLT. Общий HTTP-модуль устанавливается командой `pip install .` в Python-окружение раннера. Доступность исходных tools по пути также необходима: builder не встраивает их в toolpack. Подключите шесть инструментов к ToolHub обычной сборкой toolpack. `manifest.json` описывает состав исходного пакета и не является готовым экспортом конфигурации ToolHub.

Передавайте JSON в stdin и закрывайте его либо используйте аргумент JSON. Открытый незакрытый stdin может привести к ожиданию ввода в TWYLT. Для `sleep` тайм-аут ToolHub должен превышать `seconds` с запасом; команда действительно блокирует работника до завершения. Длительное ожидание желательно выполнять на выделенном работнике. Тайм-ауты ToolHub для сетевых команд также должны превышать их `timeout`.

## Команды

### echo

Запрос:

```json
{"text":"Привет, TWYLT!"}
```

Ответ:

```json
{"text":"Привет, TWYLT!"}
```

Обязательный параметр `text` — строка. Возвращается без изменений: сохраняются пробелы, переносы строк, Unicode и пустая строка. Команда не использует сеть и работает при `TWYLT_GUARDRAILS=1 TWYLT_DISABLE_NETWORK=1`.

### sleep

```json
{"seconds": 2.5}
```

`seconds`: 0–86400, допускает дробные значения. Возвращает `requested_seconds` и измеренное монотонными часами `elapsed_seconds`. Фактическое ожидание может быть дольше запрошенного из-за планировщика ОС.

### wget

```json
{"url":"https://example.com/","output_path":"example.html","overwrite":false,"timeout":30,"max_bytes":10000000}
```

GET-загрузка в обязательный `output_path`. Дополнительные параметры: `headers` (объект), `follow_redirects` (по умолчанию true, до 10 переходов). Только HTTP/HTTPS; рекурсивная загрузка, FTP и resume не реализованы. Ошибочный HTTP-статус не записывается в файл. Файл сначала записывается во временный файл, затем публикуется атомарно; по умолчанию существующий файл не заменяется. Контроль лимита выполняется по реально полученным байтам.

### curl

```json
{"url":"https://example.com/","method":"GET"}
```

```json
{"url":"http://localhost:8080/api","method":"POST","headers":{"Accept":"application/json"},"json_body":{"enabled":true}}
```

```json
{"url":"https://example.com/","output_path":"response.html","overwrite":true}
```

Методы: GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS. `body` — строка UTF-8; `json_body` — JSON-значение, кроме null (null означает отсутствие тела). Они взаимоисключающие. Для буквального JSON null используйте `body:"null"` и `Content-Type: application/json`. `encoding` задаёт кодировку ответа; иначе берётся charset из Content-Type или UTF-8. Если декодирование невозможно, ответ помещается в `body_base64`. Сохранение в файл использует ту же политику, что и wget.

Оба HTTP-инструмента возвращают `status`, `ok`, `headers`, `bytes_received`, `sha256`, `elapsed_seconds` и `output_path` либо `text`/`body_base64`. HTTP 4xx/5xx — обычный результат с `ok:false`; DNS, TLS, превышение лимита и тайм-аут — бизнес-ошибки TWYLT. При редиректе на другой origin пользовательские секретные заголовки не пересылаются. Не передавайте токены в query URL, если предполагается редирект.

`timeout`: 0–600 секунд (строго больше нуля); ограничивает ожидание сокета и проверяемый между блоками общий срок. Это не строгий wall-clock предел: разрешение DNS и текущая операция чтения могут задержать проверку. Строгий предел обеспечивает тайм-аут процесса в ToolHub. `max_bytes`: 1–1 000 000 000; по умолчанию 10 MB. Ответ буферизуется в памяти, поэтому для больших загрузок учитывайте лимит памяти работника. Content-Encoding автоматически не распаковывается; для бинарного/сжатого ответа предпочтительно сохранение в файл. Серверные заголовки возвращаются без удаления чувствительных данных.

### ping

```json
{"host":"127.0.0.1","count":4,"timeout":10,"family":"auto"}
```

`count`: 1–100; `family`: auto/ipv4/ipv6; `timeout`: общий предел процесса, до 300 секунд. Возвращает `reachable`, `timed_out`, `returncode`, `stdout`, `stderr`, `elapsed_seconds`. Потеря пакетов отражается системным выводом; `reachable` определяется кодом завершения ping. ICMP не проверяет доступность конкретного TCP-порта или HTTP-сервиса. Недоступность ICMP может означать фильтрацию, а не отсутствие хоста.

Команда запускается без shell, пользователь не может передавать произвольные аргументы. В контейнере ping может потребовать разрешения ICMP ОС (`ping_group_range` или `CAP_NET_RAW`, зависит от образа/ядра).

### web_search

```json
{"query":"TWYLT github","limit":10,"page":1,"language":"all","categories":"general","safe_search":1}
```

Использует `TWYLT_SEARXNG_URL` — базовый URL своего SearXNG (без `/search`, query или fragment). В настройках SearXNG нужно включить JSON:

```yaml
search:
  formats:
    - html
    - json
```

Параметры: `query`, `limit` (1–100 результатов с одной страницы), `page` (1–100), `language`, `categories`, `safe_search` (0/1/2), опционально `time_range` (day/month/year), `timeout`. Возвращает `query`, `page`, `results` (title/url/snippet/engines), `suggestions`, `number_of_results`. Число результатов может отсутствовать или быть оценкой поискового сервиса. Результаты не означают загрузку содержимого найденных страниц. Публичный SearXNG по умолчанию не выбирается: у многих инстансов JSON API отключён.

Протокол: https://docs.searxng.org/dev/search_api.html

## Проверка и разработка

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_tools.py
.venv/bin/python scripts/export_schemas.py
```

Редактируйте конкретный tools/<name>/tool.py и общий src/twylt_pack_essential/http.py. Генератора встроенных копий больше нет. Тесты используют локальный HTTP-сервер и mock системного ping, не требуют внешней сети или установленного ping. Реальный внешний поиск и ICMP в вашем окружении следует проверить отдельно после настройки. Архитектурные решения: `docs/adr/0001-essential-pack.md`.

## Миграция 0.2.0

Установите сначала TWYLT 1.1.0, затем этот пак. Общий модуль входит в Python-пакет;
requirements.txt перечисляет зависимости и не заменяет `pip install .`.
Релизы в этих архивах не опубликованы автоматически в PyPI или GitHub.

Guardrails теперь выключены по умолчанию вне toolhub-images. Для сохранения
прежних ограничений явно задайте TWYLT_GUARDRAILS=1 и workspace. Старый параметр
TWYLT_ESSENTIAL_DISABLE_NETWORK заменён TWYLT_DISABLE_NETWORK и больше не читается.
Сетевой запрет действует при включённой политике. Корректность URL, безопасные
аргументы ping, лимиты и атомарная публикация загрузки остаются обязательными.

Бизнес-пути не зависят от cwd. При выключенной политике без workspace абсолютные
пути обозначают ФС хоста; при заданном workspace сохраняется виртуальная семантика.
Механизмы TWYLT защищают от типового неосторожного использования. Автор тула отвечает
за вызовы проверок; произвольные обращения контролируются ОС.

Builder 0.4.1 совместим без изменения кода: сканируйте tools/ с glob */tool.py
(либо стандартным рекурсивным glob), устанавливайте модуль в окружение и сохраняйте
исходные пути. Не переносите только toolpack на другой хост без исходных файлов.
Пересоберите toolpack после замены tools и обновления путей.
