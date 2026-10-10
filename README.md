# club-contracts

Контракт между сервером клуба и клиентской частью (агент, шелл, касса `apps/admin`).
Источник истины — схемы в этом репозитории, не markdown и не C#.

```
openapi/base.yaml          корень OpenAPI: info, servers, securitySchemes, parameters, headers, responses
openapi/fragments/*.yaml   пути и схемы по доменам (paths-*, schemas-*)
openapi/openapi.yaml       СОБРАННЫЙ файл — генерируется, руками не править
asyncapi/asyncapi.yaml     WebSocket wss://…/ws/agent, сабпротокол clubshell.v1
scripts/bundle.py          сборка openapi.yaml, проверка дубликатов и висячих $ref
docs/OPEN_QUESTIONS.md     открытые вопросы и расхождения между кодом клиента, моком и SERVER_API.md
docs/SHELL_CHANGES.md      что нужно поменять в club-shell (для разработчика шелла)
```

## Правила

1. **Сначала схема, потом реализация.** Любая правка — PR сюда с ревью обеих сторон (сервер и шелл).
2. **Совместимость.** Поля добавлять можно всегда. Удалять и переименовывать — только в новой версии
   `/api/v2`. `additionalProperties: false` не ставится нигде: агент пропускает незнакомые поля
   (`UnmappedMemberHandling.Skip`). **Новое значение enum в ответе сервера — ломающее изменение:** агент разбирает
   enum через `JsonStringEnumConverter` без запасного значения (`Serialization/JsonDefaults.cs:113-121`), и незнакомая
   строка роняет разбор всего ответа. Новые значения — только после того, как агент научится их пропускать.
   Агент с club-shell `feat/shell-changes` (`docs/SHELL_CHANGES.md`, п. 3) научился для enum, помеченных
   `x-agent-fallback: unknown`: незнакомую строку он читает как `unknown` (само `unknown` на провод не входит).
   `ErrorCode` и остальные enum строгие, старые агенты — тоже. Каждое новое значение помечается в схеме
   `x-enum-added: { <значение>: <какой релиз потребителя его знает и что делают старые> }`.
   В CI ломающие изменения относительно базовой ветки ловит `oasdiff breaking`.
3. **`x-server-status`** на каждой операции: `required` — сервер v1 реализует; `notImplemented` — сервер
   отвечает `501`, никогда не `404`. Агент не ретраит 4xx, кроме 401/408/429, а флаги
   `features` в `GET /agents/{pcId}/config` скрывают выключенные разделы.
   **Оговорка про старых агентов:** агент до club-shell `feat/shell-changes` считает 501 временной ошибкой,
   повторяет запрос и засчитывает его в общий circuit breaker (`docs/SHELL_CHANGES.md`, п. 1 — исправлено в этой
   ветке: 501 = `notImplemented`, не повторяется). Для старых агентов 501 безопасен только на вызовах, которые они
   сами не делают. Новая операция со статусом `required` обосновывается в `x-server-note`.
4. **Имена схем = имена C#-типов** из `ClubShell.Contracts`; `PagedResult<T>` → `<T>Page`; схемы кассы
   без C#-аналога — с префиксом `Admin`. У схем `x-csharp`, у операций `x-source` — ссылки на код клиента.
5. **Запрещено в продукте:** Telegram в любом виде, пароль аккаунта в командной строке лаунчера.
   Такие операции — `notImplemented`, поля — `x-prohibited`.

## Сборка

```bash
python3 scripts/bundle.py
```

Проверка, что собранный файл актуален (для CI):

```bash
python3 scripts/bundle.py --check
```

## Линт и валидация

Нужны Python 3 с PyYAML и Node.js ≥ 22.12 (версии инструментов закреплены в `package.json`).

```bash
npm install
npm run bundle          # = python3 scripts/bundle.py
npm run lint:openapi    # Redocly CLI, правила в redocly.yaml
npm run lint:asyncapi   # AsyncAPI CLI validate (ссылки ../openapi/openapi.yaml#/components/schemas/X)
npm run check           # bundle --check + оба линта (для CI)
```

Ошибки линта блокируют `check`, предупреждения — нет. `no-unused-components` ожидаемо предупреждает о схемах,
которые используются только из `asyncapi.yaml` или описывают IPC-типы. Телеметрия AsyncAPI CLI в скрипте выключена
(`scripts/asyncapi-analytics.json`).
