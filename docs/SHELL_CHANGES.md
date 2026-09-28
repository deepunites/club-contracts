# Правки на стороне club-shell — список для разработчика шелла

Составлено 2026-09-26 со стороны сервера по коду `club-shell` (ветка main из архива `club-shell-main.zip`).
Ссылки — от корня `club-shell`. Каждый пункт проверен по коду: **[вручную]** — проверил человек со стороны сервера,
**[проверено]** — подтверждено отдельной сверкой по коду (с уточнениями, где утверждение оказалось неточным).

Приоритеты: **P0** — без этого сервер v1 или бездиск не работают надёжно; **P1** — античит, безопасность, деньги;
**P2** — улучшения. Порядок работы как договаривались: сначала правка схемы в `club-contracts`, потом код.

Часть пунктов прежнего документа «Бездиск: разделение работ» (2026-09-22) в коде уже сделана и сюда не вошла:
4xx не ретраятся (п. 2), `pcId` и номер ПК приходят от сервера (п. 6), белый список каталогов античитов при сбросе
профиля есть (п. 8), защита обновлений не выключается молча (п. 10), `SecureBootChecker` ловит `nointegritychecks`
и отладку ядра (V6).

**Статус на 2026-09-28:** п. 1–18 сделаны в club-shell, ветка `feat/shell-changes` (не смёржена; строка «Статус» под каждым пунктом называет файлы); схема под них — ветка `shell-changes-p0-p1` этого репозитория. П. 19–21 — решения владельца, не начаты.

---

## P0 — связь агента с сервером

### 1. Ответ 501 считается временной ошибкой и валит всё соединение [вручную]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Core/Http/RetryPolicy.cs` (501 не временный, не в circuit breaker), `src/ClubShell.Contracts/Errors/ErrorCode.cs` (`NotImplemented`, `notImplemented`, 501, не retryable), `src/ClubShell.Core/Http/ServerClient.cs` (`ParseServerError`: при неизвестном `code` сохраняются message/details/traceId), `src/ClubShell.Agent/Ipc/Handlers/SystemHandlers.cs` (callAdmin уходит в телеметрию и на `notImplemented`); тесты — `tests/ClubShell.Core.Tests/ServerClientTests.cs`. Схема: `ErrorCode.notImplemented` (`x-enum-added`), ответ `NotImplemented` теперь с `code = notImplemented`, `info.description` §4, §8.

- `src/ClubShell.Core/Http/RetryPolicy.cs:55` — `status is 408 or 425 or 429 || status >= 500`, т. е. 501 временный.
  Идемпотентные запросы повторяются до 5 раз (`AppSettings.cs:242`), каждая попытка идёт через общий circuit breaker
  (`RetryPolicy.cs:113-120`, `FailureRatio 0.8`, окно и размыкание 30 с). Один GET на нереализованный эндпоинт может
  разомкнуть breaker, и на 30 с падают все вызовы, включая heartbeat и сессии.
- В `ErrorCode` нет значения для 501 (`src/ClubShell.Contracts/Errors/ErrorCode.cs:14-75`). Неизвестный `error.code`
  роняет разбор всего конверта; `ServerClient.ReadErrorAsync` (`ServerClient.cs:589-610`) глотает исключение, код
  берётся по статусу → `ServerUnavailable`, message/details/traceId теряются.
- **Просим:** исключить 501 из `IsTransient` (`status >= 500 && status != 501`), добавить `ErrorCode.NotImplemented`
  (не retryable), при неизвестном `code` сохранять message/traceId из тела.
- Зачем нам: сервер v1 отвечает 501 на всё, что не реализовано (`x-server-status: notImplemented` в контракте).

### 2. Повторы запроса уходят с той же подписью [вручную]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Core/Http/RequestSigningHandler.cs` (новый `DelegatingHandler` внутри конвейера повторов, `RetryPolicy.cs`): каждая попытка подписывается заново, повтор в ту же секунду получает `X-Timestamp` + 1. Формат заголовков не изменился. Остаётся открытым: два одинаковых логических запроса в одну секунду дают тот же кортеж (nonce нет) — `docs/OPEN_QUESTIONS.md`, base; схема — `info.description` §3.

- Подпись ставится один раз в `ServerClient.Authorize` (`ServerClient.cs:774`, `825-832`), а повторы Polly идут
  внутри `HttpClient` (`RetryPolicy.cs:155`, `AddResilienceHandler`). Все попытки несут одинаковые `X-Timestamp`
  и `X-Signature`.
- Сервер защищается от повторов по тройке `(pcId, X-Timestamp, X-Signature)` — он отклонит каждую повторную попытку.
- **Просим:** подписывать каждую попытку заново — перенести подпись в `DelegatingHandler` внутри resilience-конвейера
  (после retry).

### 3. Новые значения enum ломают старых агентов [вручную + проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Contracts/Serialization/JsonDefaults.cs` (`CamelCaseEnumConverter`: у enum с членом `Unknown` незнакомая строка → `unknown`), 22 enum получили `Unknown` (`Commands/ServerCommand.cs`, `Games/LauncherType.cs`, `Ipc/IpcMessage.cs`, `Pc/PcInfo.cs`, `Pc/PcStatus.cs`, `Session/*.cs`, `Shop/*.cs`, `Users/*.cs`, `Wallet/Transaction.cs`), `ServerCommandEnvelope.Name` — строка; неизвестная команда в REST-пачке получает ack `notFound` (`src/ClubShell.Agent/Server/Heartbeat.cs`). `unknown` на сервер не уходит (`Session/SessionManager.cs`, `Updates/AgentUpdater.cs`, `Ipc/Handlers/PolicyHandlers.cs`). `ErrorCode` остаётся строгим. Схема: `x-agent-fallback: unknown` на этих enum, `ServerCommandEnvelope.name: string`, правило `x-enum-added` (README, правило 2; `info.description` §9).

- Все enum разбираются через `JsonStringEnumConverter` без запасного значения
  (`src/ClubShell.Contracts/Serialization/JsonDefaults.cs:113-120`): незнакомая строка роняет разбор всего ответа.
- Хуже всего в `GET /agents/{pcId}/commands`: `ServerCommandEnvelope.Name` — enum (`ServerCommand.cs:208`),
  одно неизвестное имя команды ломает всю пачку (`Heartbeat.cs:267-272`), ни одна команда не выполняется и не
  получает ack, и так на каждом heartbeat. По WebSocket то же сделано правильно — строка + `TryParse` + ack `notFound`
  (`RealtimeClient.cs:371-380`).
- **Просим:** `ServerCommandEnvelope.Name` сделать строкой, как `WsFrame.Name`; на неизвестные команды отвечать ack
  `ok:false, notFound`. Для остальных enum в ответах сервера — запасное значение `unknown` вместо исключения.

### 4. Флаги фич по умолчанию включены, часть вызовов флагами не закрыта [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Agent/Ipc/Handlers/PolicyHandlers.cs` (нет флага → false для shop/chat/booking/tournaments/topup), `config/shell.default.json`, `apps/shell/src/store/settings.ts`; `src/ClubShell.Agent/Server/CommandReceiver.cs` (блок shell применяется первым и отдельно); `src/ClubShell.Agent/Ipc/Handlers/SessionHandlers.cs` (`OrdersAsync` закрыт `features.shop`); `src/ClubShell.Contracts/Pc/PcInfo.cs` + `src/ClubShell.Core/Configuration/AppSettings.cs` + `src/ClubShell.Core/Updates/UpdateChecker.cs` (`updates.enabled`), `AgentServerConfig.anticheat` → `src/ClubShell.Core/Configuration/SettingsLoader.cs`. Схема: `UpdatesConfigOverride.enabled`, `AgentServerConfig.anticheat`, описания `ShellConfigOverride.features`, `ShellFeatures`, `GET /shop/orders`.

- Отсутствующий флаг = `true` (`src/ClubShell.Agent/Ipc/Handlers/PolicyHandlers.cs:251-252`, `270-278`),
  в `config/shell.default.json:56-65` все флаги `true`, во фронте так же (`apps/shell/src/store/settings.ts:31-40`).
  Если серверный конфиг не применился (например, ошибка валидации другой секции в
  `CommandReceiver.RefreshServerConfigAsync`, `CommandReceiver.cs:527-531`), все разделы остаются включёнными.
- Без флага идут автоматически: `GET /wallet/{userId}/balance`, `GET /shop/orders`, `GET /tariffs` при каждом входе
  (`apps/shell/src/store/index.ts:42-48`, `SessionHandlers.cs:636-666`, `785-791`); `GET /pcs/{pcId}` при старте
  шелла (`settings.ts:136-139` → `SystemHandlers.cs:433-455`); опрос обновлений без возможности выключить
  (`AgentUpdater.cs:224-229`, `UpdateChecker.cs:135-148`; в `UpdatesConfigOverride` нет `enabled`);
  `POST /anticheat/report` выключается только локально (`AntiCheatMonitor.cs:354`, в `AgentServerConfig` нет секции
  `anticheat`).
- **Просим:** fallback `false` для shop/chat/booking/tournaments/topup; `ApplyShellOverride` в отдельном `try`;
  `OrdersAsync` закрыть `features.shop`, как `ProductsAsync`; добавить `updates.enabled` и секцию `anticheat`
  (`reportViolations`) в серверный конфиг.

### 5. Пул аккаунтов и облачные сейвы включены по умолчанию [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Core/Configuration/AppSettings.cs`, `config/agent.default.json`: `games.accountPool.enabled` и `games.cloudSave.enabled` по умолчанию `false`. Схема: `default: false` и описания в `AgentServerConfig.games`.

- `games.accountPool.enabled = true`, `games.cloudSave.enabled = true` (`AppSettings.cs:437`, `:451`,
  `config/agent.default.json:60-61`). Агент берёт аренду аккаунта при `UseAccountPool || game.RequiresAccount`.
- Пул аккаунтов — открытый продуктовый вопрос (Q8); сервер v1 эти эндпоинты не реализует.
- **Просим:** дефолт `false` для обоих; включать только сервером. (Сервер v1 будет отдавать `requiresAccount: false`.)

### 6. WebSocket [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена): токен только в `Authorization` — `src/ClubShell.Core/Realtime/RealtimeClient.cs` (мок принимает оба способа — `tools/MockServer/src/ws.ts`); refresh за 2 мин до `exp` + переподключение — `src/ClubShell.Agent/Server/ServerConnection.cs`; ack на дубли и ack power-команд на диске 24 ч (`cache/power-acks.json`) — `src/ClubShell.Agent/Server/CommandReceiver.cs`; `launch-report` в outbox — `src/ClubShell.Agent/Session/OfflineSessionStore.cs`, `Games/GameLaunchService.cs`, `Games/GameSessionTracker.cs`; телеметрия (≤ 100 событий в пачке, 4xx кроме 401/408/429 — пачка отбрасывается, backoff до 15 мин) — `src/ClubShell.Agent/Server/TelemetryReporter.cs`; §6/§6.2 — `docs/SERVER_API.md`, `docs/SECURITY.md`. Схема: `asyncapi.yaml` §1, §2, §7, §8, bindings; `TelemetryBatch`, `sendTelemetry`, `sendLaunchReport`.

- **Токен в query-строке.** Агент шлёт JWT и в `Authorization: Bearer`, и в `?token=` (`RealtimeClient.cs:107`,
  `267-268`); документ описывает только query. Сервер примет оба. **Просим** со временем убрать `?token=` — JWT
  попадает в access-логи прокси — и дописать в `SERVER_API.md` §6.
- **Истечение токена на живом сокете.** Упреждающего refresh нет, после refresh сокет не переподключается
  (`Reconnector.cs:116` — у `TriggerReconnect` нет вызовов). Сервер будет закрывать сокет кодом 4401 по `exp` — агент
  на это корректно восстанавливается (`ServerConnection.cs:284-288`). **Просим** зафиксировать это в `SERVER_API.md`
  или добавить таймер refresh + `TriggerReconnect`.
- **Повторная reboot/shutdown после перезапуска.** Дедупликация команд только в памяти (`RealtimeClient.cs:51`,
  `CommandReceiver.cs:86`); если ack не ушёл до выключения, после загрузки команда выполнится снова. Дубликат в
  `RealtimeClient.cs:365-368` молча игнорируется без ack. **Просим** хранить id выполненных power-команд 24 ч на диске
  и на дубликат отвечать закэшированным ack. (Сервер со своей стороны ставит `expiresAt` у power-команд.)
- **События агента.** `sessionStarted/sessionEnded/gameLaunched/gameExited` агент не шлёт вообще (источник истины —
  REST: `POST /sessions`, `/sessions/{id}/end`, `/games/{id}/launch-report`); офлайн WS-события отбрасываются
  (`DependencyInjection.cs:471-496`), хотя `SERVER_API.md` обещает outbox; `launch-report` при ошибке не ставится в
  outbox (`GameLaunchService.cs:471-474`, `GameSessionTracker.cs:232-235`). **Просим** привести §6.2 в соответствие с
  кодом (или начать слать события) и класть `launch-report` в outbox.
- **Телеметрия.** Пачка событий не делится (до 1024 после офлайна, `TelemetryReporter.cs:96`), любой 4xx блокирует
  всю телеметрию навсегда и повторяется на каждом тике без backoff. **Просим** лимит событий в пачке (например, 100),
  на 4xx (кроме 401/408/429) отбрасывать пачку, после неудачи — backoff.

---

## P0 — бездиск: монтирование тома с играми

### 7. Порядок монтирования iSCSI: сейчас том успевает смонтироваться на запись [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) (по-другому): iSCSI агент больше не монтирует вовсе — это работа ClubDisklessHelper (club-shell `docs/DISKLESS.md`, SAN policy/RO до online — на стороне помощника). `src/ClubShell.Windows/Storage/IscsiInitiator.cs` удалён; `src/ClubShell.Agent/Storage/GamesShareMounter.cs`: `storage.gamesShare.iscsi` != null → ничего не монтируется (fail closed) и ошибка в лог; при установленном помощнике агент не трогает том. SMB-режим для агента оставлен. Схема: `AgentServerConfig.storage` (iscsi — устаревший слот, `readOnly` не читается).

- SAN policy нигде не выставляется (grep по `src/` пусто). На клиентской Windows (`OnlineAll`) диск сам выходит online
  и монтирует NTFS на запись, с первой свободной буквой, не обязательно `G:`; на `OfflineShared` диск остаётся offline,
  и агент ждёт `G:` вечно.
- Атрибут read-only ставится **после** логина к таргету (`GamesShareMounter.cs:313-323`, `IscsiInitiator.cs:237-295`),
  т. е. после того как диск отдан PnP. За это окно NTFS пишет `$LogFile`/dirty bit, может создать
  `System Volume Information`, индексатор и Defender трогают том. Если `MSFT_Disk` ещё не видит диск, метод тихо
  возвращает 0 и том остаётся на запись.
- `IscsiSettings.ReadOnly` по умолчанию `false` (`AppSettings.cs:552`); при `iscsi: null` выбирается SMB
  (`GamesShareMounter.cs:134-136`, `config/agent.default.json:73-79`).
- **Просим (fail-closed):** до логина — `san policy=OfflineShared`; после логина дождаться диска именно этого таргета
  (`MSFT_iSCSISession` → `MSFT_Disk`), `attributes disk set readonly`, проверить `IsReadOnly = true`, и только потом
  `online disk` и назначение буквы. Любая ошибка или неподтверждённый RO → `LogoutAsync` и отказ, а не монтирование на
  запись. `ReadOnly` по умолчанию `true`. SMB для игр с античитом не использовать (часть античитов не стартует с
  сетевого пути) — лучше убрать SMB-режим для игрового тома совсем.
- Зачем нам: один клиент, записавший в общий LUN, ломает том всем остальным (20–50 ПК на одном клоне ZFS).

### 8. Смена тома с сервера [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Agent/Storage/GamesShareMounter.cs` (подписка на смену настроек: enabled/uncPath/driveLetter действуют сразу, при смене пути старая буква отключается), `src/ClubShell.Core/Configuration/SettingsLoader.cs` (последний `AgentServerConfig` целиком в `<paths.cache>/server-config.json`, применяется при старте). Схема: описания `AgentServerConfig`, `AgentServerConfig.storage`.

- `enabled` читается только в `StartAsync` (`GamesShareMounter.cs:84-97`): включение с сервера не запускает цикл,
  выключение не останавливает. Остальные поля (`targetIqn`, `driveLetter`, …) подхватываются в следующей итерации, но
  старое подключение не снимается, а `StopAsync` потом разлогинивает уже новый таргет. Серверный конфиг приходит только
  после первого heartbeat и не сохраняется на диск.
- **Просим:** реагировать на `OnChange` — при смене `enabled`/режима/`targetIqn`/`driveLetter` размонтировать по
  старому снимку и перезапускать цикл; кэшировать последний серверный конфиг на диск, чтобы `storage.gamesShare` с
  сервера работал с первой загрузки.
- Зачем нам: публикация новой версии библиотеки = переключение на новый клон ZFS; обходить 50 машин руками нельзя.

### 9. Поведение при недоступном таргете и перезапуске службы [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Agent/Storage/GamesShareMounter.cs` (исправное подключение только проверяется; остановка/обновление службы диск не отключает), `src/ClubShell.Agent/Server/Heartbeat.cs` + `src/ClubShell.Contracts/Commands/ServerCommand.cs` (`HeartbeatRequest.gamesVolume`). Схема: `HeartbeatGamesVolume`, `GamesVolumeOwner`.

- Подключение не persistent (комментарии в коде утверждают обратное, `IscsiInitiator.cs:127-148`); недоступный портал
  не блокирует загрузку — хорошо. Но: даже со смонтированным диском агент каждые 30 с заново запускает `sc.exe` и
  `iscsicli QAddTargetPortal` (`GamesShareMounter.cs:93-96`), и короткий сбой портала помечает том потерянным; при
  остановке/обновлении службы таргет разлогинивается под играющим пользователем.
- **Просим:** не трогать портал, если `IsConnectedAsync(targetIqn)`; в `StopAsync` не разлогинивать при
  перезапуске/обновлении службы; передавать состояние игрового тома (смонтирован, IQN, RO, с какого времени) в
  heartbeat — панели нужно видеть, у кого том отвалился.

### 10. Правка файлов на общем томе при запуске Steam [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Agent/Games/Accounts/AccountInjector.cs` (автологин Steam сбрасывается в `HKU\<kioskSID>\Software\Valve\Steam`: `AutoLoginUser`, `RememberPassword`; `loginusers.vdf` — best effort), `src/ClubShell.Contracts/Games/LaunchRequest.cs` (`LaunchReport.InjectionError`), `src/ClubShell.Agent/Games/GameLaunchService.cs`. Q1 (Steam с тома только для чтения) — по-прежнему на стенде. Схема: `LaunchReport.injectionError`.

- `AccountInjector` пишет `<SteamDir>\config\loginusers.vdf` (`AccountInjector.cs:371`). На томе только для чтения
  запись падает с warning, игра запускается дальше, и может автоматически войти предыдущий аккаунт. Резервная копия
  файла только в памяти.
- **Просим:** сбрасывать автологин через профиль kiosk (`HKU\<kioskSID>\Software\Valve\Steam\AutoLoginUser = ""`,
  `RememberPassword = 0`), `loginusers.vdf` — best-effort; неудачу возвращать в `LaunchReport`, а не только в лог.
- Связано с открытым вопросом Q1 (Steam с тома только для чтения) — проверяется на стенде.

---

## P1 — античит и безопасность

### 11. Пароль аккаунта в командной строке лаунчера [вручную + проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Agent/Games/Accounts/AccountInjector.cs` (`CredentialArgs`), `Games/Launchers/SteamLauncher.cs`, `Games/Launchers/EpicLauncher.cs`: Steam и Epic берут сессию из `extra.files`, Epic — одноразовый exchange-код (`extra.authType = "exchangeCode"`); пароль — только при `games.accountPool.allowPasswordOnCommandLine = true` (по умолчанию false, `src/ClubShell.Core/Configuration/AppSettings.cs`), `docs/GAME_LAUNCHERS.md`. Проверка поведения Steam/Epic — на стенде. Схема: `AccountLease.secret`/`extra`, `AgentServerConfig.games.accountPool.allowPasswordOnCommandLine`.

- Steam: `-login <user> <password>` (`AccountInjector.cs:401`); Epic: `-AUTH_LOGIN=… -AUTH_PASSWORD=…` (`:457`).
  Пароль виден любому процессу сессии игрока (WMI `Win32_Process.CommandLine`, Диспетчер задач) всё время работы
  лаунчера. В продукте это запрещено.
- **Просим:** убрать пароль из аргументов (Steam — сессия из файлов/реестра, как уже сделано для Riot и Battle.net;
  Epic — одноразовый exchange code от сервера); до этого путь с паролем закрыть настройкой, выключенной по умолчанию.

### 12. Удалённый ввод во время игры с античитом [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Core/Configuration/AppSettings.cs`, `config/agent.default.json` (`remoteAdmin.allowRemoteInput` = false), `src/ClubShell.Agent/Remote/RemoteInput.cs` (ввод отбрасывается, пока идёт отслеживаемая игра с античитом). Схема: `AgentServerConfig.remoteAdmin.allowRemoteInput`.

- `SendInput` без проверки активной игры с античитом (`RemoteInput.cs:216`, `:459`); `AllowRemoteInput = true` по
  умолчанию (`AppSettings.cs:646`, `config/agent.default.json:104`). Сверка показала, что из session 0 ввод на рабочий
  стол киоска, скорее всего, вообще не попадает; если перенести в пользовательскую сессию — синтетический ввод под
  Vanguard/FACEIT/EAC грозит флагом.
- **Просим:** дефолт `false`; отклонять ввод, пока запущена игра с `AntiCheat != None`.

### 13. Веб-фильтр может заблокировать CDN лаунчеров [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Contracts/Pc/PcInfo.cs` (`WebFilterPolicy.BlockResolvedIps`, по умолчанию false; `ProtectedDomains`), `src/ClubShell.Agent/Policy/WebFilterPolicy.cs` (+ хост `server.baseUrl`), `src/ClubShell.Windows/Network/DnsFilter.cs`, `config/policies.example.json`. Схема: `WebFilterPolicy.blockResolvedIps`, `protectedDomains`.

- Защищённый список доменов есть, но резолвятся только apex и `www.` (`WebFilterPolicy.cs:160`), не реальные сервисные
  хосты; anycast-IP Cloudflare/Akamai/Fastly, совпавший с заблокированным сайтом, блокируется; устаревшие IP держатся
  в правилах; список нельзя расширить с сервера.
- **Просим:** IP-блокировку сделать опциональной (`webFilter.blockResolvedIps`, по умолчанию `false`), добавить
  `webFilter.protectedDomains` от сервера плюс хост `server.baseUrl`.

### 14. Состояние античитов для сервера [проверено; исходное утверждение опровергнуто]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `src/ClubShell.Agent/Games/GameLaunchService.cs` (`EffectiveAntiCheat`: Riot без пометки → vanguard), `src/ClubShell.Agent/Server/Heartbeat.cs` + `src/ClubShell.Contracts/Commands/ServerCommand.cs` (`HeartbeatRequest.antiCheat`: vgk установлен/загружен, Secure Boot, TPM). Схема: `HeartbeatAntiCheat`, описание `AntiCheatKind`.

- Отказ запуска без Vanguard уже есть: игра с `antiCheat: "vanguard"` в каталоге или `policy.anticheat.required` →
  `antiCheatBlocked`. Пробелы: Riot-игра проверяется, только если каталог пометил её `vanguard` (нет соответствия
  `LauncherType.Riot → Vanguard`); `policy.anticheat.required` не применяется к играм с `AntiCheat = None`
  (`GameLaunchService.cs:417-420`).
- **Просим:** подставлять Vanguard для Riot-игр без явной пометки; передавать в инвентарь/heartbeat состояние
  античитов (`vgk` установлен/загружен, Secure Boot, TPM), чтобы сервер скрывал Riot-игры на ПК и образах без Vanguard.

---

## P1 — касса (`apps/admin`)

### 15. Денежные операции без Idempotency-Key [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `apps/admin/src/api.ts` (`postMoney`: один ключ на действие, тот же при повторе после сети/5xx) на семи маршрутах, мок — `tools/MockServer/src/routes/admin.ts`, `routes/club.ts` (`idempotent`), тест — `tests/shell-e2e/admin/console.spec.ts`. Схема: `IdempotencyKeyOptional` (+ на `POST /admin/shift/close`), `info.description` §5, §11 (CORS).

- `call()`/`post()` (`apps/admin/src/api.ts:89-116`) не шлют `Idempotency-Key`. При сетевом таймауте кассир нажмёт
  ещё раз — деньги спишутся или начислятся дважды. От двойного клика защищает только `busy` в `MapPage.tsx`.
- **Просим:** `Idempotency-Key` (`crypto.randomUUID()` один раз на действие, тот же при повторе) для openSession,
  extend, end, topUp, redeemPromo, receiveProduct, closeShift.

### 16. API-ключ клуба приходит кассиру [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `apps/admin/src/api.ts` (`apiKey?: string`, `clubApi.apiKey()`, `clubApi.logout()`), `apps/admin/src/App.tsx` (выход вызывает сервер), `apps/admin/src/pages/IntegrationsPage.tsx`; мок — `tools/MockServer/src/routes/club.ts` (`GET /admin/club` без `apiKey`, `GET /admin/club/api-key` только владельцу, `POST /admin/logout`). Схема: новые `GET /admin/club/api-key`, `POST /admin/logout` (оба required), `AdminClubSettings.apiKey` — deprecated и не отдаётся.

- `GET /admin/club` отдаёт `apiKey` любому сотруднику; страницы кассира «Клиенты» и «Магазин и склад» грузят весь
  документ, ключ виден в DevTools. Показывается он только владельцу, но в JSON приходит всем.
- Сервер перестанет отдавать `apiKey` в `GET /admin/club`. **Просим:** `apiKey?: string` в типах, ключ брать из
  отдельного owner-only запроса; «Выйти» (`App.tsx:417`) — вызывать серверный `POST /admin/logout` (предложим в
  контракт), а не только чистить localStorage.

### 17. Telegram [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — раздел и поле убраны: `apps/admin/src/pages/IntegrationsPage.tsx`, `pages/ClientsPage.tsx`, `apps/admin/src/api.ts`; мок без Telegram — `tools/MockServer/src/club.ts`, `db.ts`, `routes/club.ts` (`POST /admin/notifications/test` удалён), `apps/shell/src/mocks/data.ts`, `README.md`. Схема: Telegram-поля `AdminNotifications`/`AdminClient` — необязательные и deprecated, `adminTestNotification` — deprecated (удаление — в `/api/v2`).

- Telegram в продукте запрещён. В кассе: раздел в `IntegrationsPage.tsx`, поле клиента в `ClientsPage.tsx`; типы в
  `api.ts:285-290`, `:437` объявлены обязательными — без поля Telegram нельзя сохранить правку клиента. В моках —
  приложение Telegram в каталоге (`tools/MockServer/src/db.ts:1193-1210`, `apps/shell/src/mocks/data.ts:602-609`) и
  реальная отправка в `api.telegram.org` (`tools/MockServer/src/club.ts:564-568`).
- **Просим:** убрать раздел и поле; до удаления — сделать поля необязательными (`telegram?: string`, `notifications?`)
  и скрывать секцию, если сервер её не вернул.

### 18. Клиент, созданный на кассе, не может войти [проверено]

> **Статус: сделано** в club-shell, ветка `feat/shell-changes` (не смёржена) — `apps/admin/src/pages/ClientsPage.tsx` (пароль или сгенерированный временный, карта; «Сбросить пароль», «Привязать карту»), `apps/admin/src/api.ts`; мок — `tools/MockServer/src/routes/club.ts` (без `demo`). Схема: `AdminClient.cardId`, `AdminClientCreateRequest.password/cardId`, новые `POST /admin/clients/{id}/password` и `/card` (required), `AdminAuditAction` + `clientPassword`/`clientCard`.

- `addClient` (`api.ts:530-537`) не передаёт ни пароль, ни PIN, ни карту; в моке вход работает только из-за пароля
  `demo` по умолчанию (`routes/club.ts:427`).
- **Просим:** поле пароля (или генерация временного с показом кассиру) и номер карты в форме «Новый клиент»; действия
  «Сбросить пароль» и «Привязать карту». Схему согласуем в `club-contracts`.

---

## P2 — процесс и документация

19. **Источник истины контракта — `club-contracts`** (OpenAPI 3.1 + AsyncAPI), а не `ClubShell.Contracts` +
    `tools/ContractsGen`. Предлагаем генерировать C#-DTO из схемы (NSwag) и перенести мок-сервер в
    `club-contracts`, чтобы обе стороны гоняли один набор запросов. Расхождения `SERVER_API.md` с кодом и моком —
    в `club-contracts/docs/OPEN_QUESTIONS.md`.

    **Статус:** не начато — решение владельца (вне объёма ветки `feat/shell-changes`).
20. **Реальный прогон CI.** `README.md:385` пишет «429 xUnit tests pass», бейдж — «424», а `docs/ROADMAP.md:28` —
    «no `dotnet build` was run». Нужен настоящий прогон `dotnet build`, `cargo`, `clippy`, WiX.

    **Статус:** не начато — решение владельца (вне объёма ветки `feat/shell-changes`).
21. **Отдельный канал инвентаря** `POST /pcs/{pcId}/inventory` полным снимком при старте и при изменении — сейчас
    `HardwareInfo` едет в телеметрии (`ServerCommand.cs:845`). Нужен для экрана «Рабочие станции»; сначала схема в
    `club-contracts`.

    **Статус:** не начато — решение владельца (вне объёма ветки `feat/shell-changes`).
