# myojou live sync

Python automation for turning recent X posts from `@info_myojou` into one canonical live schedule and ticket-deadline data set.

Current shape:

- Notion remains the detailed admin/source database.
- The fan-facing production view is the static mobile web view in `public/`.
- Google Sheets support exists as a secondary sync target, but it is not started yet.
- Internal Python models and SQLite fields stay in English; public Notion, Sheets, and web output use Japanese labels.

Local tests use mock X JSON files only. Real X API access is supported for intentional dry-runs and production sync, but local defaults keep it disabled with `NO_X_API=true`. For intentional Notion sync testing, keep using `mock_posts` as input and set `DRY_RUN=false` only for that command.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Useful `.env` defaults:

```bash
X_USERNAME=info_myojou
X_MAX_RESULTS=10
NO_X_API=true
DRY_RUN=true
MYOJOU_STATE_DB=.state/myojou_sync.sqlite
MYOJOU_MOCK_POSTS=mock_posts
```

`NO_X_API=true` blocks accidental real X fetches. `MYOJOU_MOCK_POSTS=mock_posts` keeps local runs on the mock data set. Keep `DRY_RUN=true` for preview/export-only work, and use `DRY_RUN=false` only when intentionally syncing mock data to Notion.

## Current Project Status

The project currently has three layers:

| Layer | Role |
| --- | --- |
| SQLite state | Local canonical event store, processed post tracking, source lineage |
| Notion | Detailed admin/backend database for review, source checking, and manual edits |
| Static web view | Mobile-first public fan view generated from `public/events.json` |

Public users should use the mobile web view. Notion table views are useful for administration, but they are not ideal as the public smartphone UX because wide tables require horizontal scrolling.

The static public web view lives in:

```text
public/index.html
public/app.js
public/calendar_helpers.js
public/styles.css
public/events.json
```

It renders a Japanese mobile-first public UI with two views:

```text
カード
カレンダー
```

The `カード` view uses vertical event cards and these filters:

```text
今日以降
今週
今月
締切未取得
すべて
```

It also supports these sort modes:

```text
ライブ日順
申込締切順
```

Each card shows date, event name, venue, compact live/ticket/application summaries, ticket status, and a ticket URL button.
When multiple ticket sales periods are known, the card also shows compact sales-period rows and highlights the next relevant deadline.

The `カレンダー` view is optimized for live and ticket deadline management rather than a generic calendar. It renders multiple months vertically, starting with the current month, next month, and following month. Users can expand the range with:

```text
前の月を表示
次の月を表示
```

Calendar modes:

```text
ライブ日
申込締切
支払期限
すべて
```

Calendar cells show compact chips such as `ライブ`, `申込`, `支払`, `完売`, and `販売終了`. The calendar also has a `締切アラート` section for `今日締切`, `明日締切`, and `締切未取得`. Tapping a date does not open a separate selected-date list; event cards remain available in the `カード` view.

## Current Development Mode Without X API

Day-to-day development should continue without consuming X API reads:

```bash
NO_X_API=true
MYOJOU_MOCK_POSTS=mock_posts
DRY_RUN=true
```

With `NO_X_API=true`, a run that disables mock posts with `--no-mock-posts` fails before constructing the real X client. To use the real X API later, change `NO_X_API=false` intentionally and pass the required credentials.

Run tests:

```bash
.venv/bin/pytest
```

Run mock sync for preview/export-only work:

```bash
.venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/public-web-demo.sqlite \
  --target none \
  --dry-run
```

Sync mock data to Notion intentionally:

```bash
DRY_RUN=false .venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-notion.sqlite \
  --target notion \
  --no-dry-run \
  --preview table
```

Do not run Google Sheets sync yet.

Export the public web JSON:

```bash
.venv/bin/myojou-sync export-public \
  --db .state/public-web-demo.sqlite \
  --output public/events.json
```

By default, `export-public` writes only public-ready live schedule events. Suspicious parser rows, profile/member-introduction posts, blank event names, and records missing enough live structure stay in SQLite for debugging but are not published to the mobile web UI.

For parser audits only, export every canonical row including suspicious/not-public-ready records:

```bash
.venv/bin/myojou-sync export-public \
  --db .state/public-web-demo.sqlite \
  --output .state/events-debug.json \
  --include-not-public-ready
```

Run the local public web server:

```bash
python3 -m http.server 8765 --directory public
```

Open locally:

```text
http://localhost:8765/
```

Check from a smartphone on the same Wi-Fi:

```bash
ipconfig getifaddr en0
```

Then open this URL on the phone, replacing `<LOCAL_IP>`:

```text
http://<LOCAL_IP>:8765/
```

## Production-Style Incremental Sync

Real X API access should be explicit. Keep local/default development on mock posts, then use a dedicated production SQLite DB when you are ready to dry-run the real incremental workflow.

Bootstrap the production DB from the saved historical backfill fixture without calling X again:

```bash
NO_X_API=true DRY_RUN=true .venv/bin/myojou-sync run \
  --mock-posts mock_posts/real_samples/info_myojou_backfill_500.json \
  --db .state/production.sqlite \
  --target none \
  --dry-run \
  --preview table
```

This normal mock run processes the saved posts and initializes `last_seen_post_id` from the newest processed X post ID. It is useful after a backfill capture because the historical backfill command itself does not advance the incremental cursor.

Inspect local sync state:

```bash
.venv/bin/myojou-sync inspect-state \
  --db .state/production.sqlite
```

The inspection output shows the cached X user ID, `last_seen_post_id`, latest processed post timestamp, processed source post count, and canonical event count.

Run a production-like real X incremental dry-run:

```bash
NO_X_API=false DRY_RUN=true .venv/bin/myojou-sync run \
  --no-mock-posts \
  --db .state/production.sqlite \
  --target none \
  --dry-run \
  --preview table
```

Normal non-backfill real X runs use the stored `last_seen_post_id` as `since_id`, so only newer posts are requested when the cursor exists. The cursor is advanced only after the fetched batch finishes processing successfully. If a run fails mid-processing, rerun it; already saved source posts are skipped by ID and the cursor is not moved past unprocessed posts.

After a successful sync, export the public web JSON:

```bash
.venv/bin/myojou-sync export-public \
  --db .state/production.sqlite \
  --output public/events.json
```

This does not commit `public/events.json` and does not call GitHub APIs. Use a fresh or clearly named SQLite DB for backfill experiments so historical pagination does not get mixed up with production incremental state.

### Safer Public Refresh Workflow

Use `refresh-public` when the goal is specifically to update the fan-facing `public/events.json` from the production SQLite state. It always skips Notion and Google Sheets.

Bootstrap once from the saved historical backfill sample:

```bash
NO_X_API=true DRY_RUN=true .venv/bin/myojou-sync run \
  --mock-posts mock_posts/real_samples/info_myojou_backfill_500.json \
  --db .state/production.sqlite \
  --target none \
  --dry-run \
  --preview table
```

Daily/manual refresh dry-run:

```bash
NO_X_API=false .venv/bin/myojou-sync refresh-public \
  --db .state/production.sqlite \
  --output public/events.json \
  --dry-run
```

The dry-run performs the incremental X sync and validates the newly generated public JSON rows, but it does not overwrite `public/events.json`. It prints a before/after summary with event counts, added/removed/possibly changed rows, needs-review count, public-ready safety count, and earliest/latest dates.

Actual public JSON write:

```bash
NO_X_API=false .venv/bin/myojou-sync refresh-public \
  --db .state/production.sqlite \
  --output public/events.json \
  --write
```

Validate the generated file:

```bash
.venv/bin/myojou-sync validate-public \
  --input public/events.json
```

Then manually review and commit `public/events.json` if committing JSON is the intended publish mechanism. The refresh command does not auto-commit and does not call GitHub APIs.

Offline verification is explicit:

```bash
NO_X_API=true .venv/bin/myojou-sync refresh-public \
  --mock-posts mock_posts \
  --db .state/public-refresh-mock.sqlite \
  --output .state/events-preview.json \
  --dry-run
```

`refresh-public` intentionally ignores `MYOJOU_MOCK_POSTS` unless `--mock-posts` is passed. This prevents production refreshes from accidentally using demo data because of a local environment default.

## Local Development Flow

Run tests:

```bash
.venv/bin/pytest
```

Run a mock sync without any external writes:

```bash
.venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/public-web-local.sqlite \
  --target none \
  --dry-run
```

Export the public web JSON:

```bash
.venv/bin/myojou-sync export-public \
  --db .state/public-web-local.sqlite \
  --output public/events.json
```

Start the local static server:

```bash
python3 -m http.server 8765 --directory public
```

Open on this machine:

```text
http://localhost:8765/
```

Check on a smartphone on the same Wi-Fi:

```bash
ipconfig getifaddr en0
```

Then open this URL on the phone, replacing `<LOCAL_IP>`:

```text
http://<LOCAL_IP>:8765/
```

If `en0` does not return an address, check your active network interface with `ifconfig` or your macOS network settings.

## Public Web View

The public fan-facing view is a static mobile-first web app:

| File | Purpose |
| --- | --- |
| `public/index.html` | Page shell for the public schedule |
| `public/app.js` | Loads `events.json`, filters events, and renders card/calendar views |
| `public/calendar_helpers.js` | Calendar grouping, month range, deadline mode, and alert helpers |
| `public/styles.css` | Mobile-first card styling |
| `public/events.json` | Exported canonical public event data |

The UI is designed for smartphones:

- Events are vertical cards, not a table.
- Cards are grouped by date in live-date mode, and by application deadline in deadline mode.
- Ticket status is shown as a compact badge.
- Application deadline urgency is shown with badges such as `今日締切`, `明日締切`, `あと3日`, and `締切未取得`.
- Ticket URLs are large tap targets.
- Long event names and ticket summaries wrap inside the card.
- The calendar view renders vertical multi-month sections with no horizontal scrolling.
- Calendar modes show `ライブ日`, `申込締切`, `支払期限`, or `すべて`.
- Calendar cells use compact chips for `ライブ`, `申込`, `支払`, `完売`, and `販売終了`.
- `締切アラート` summarizes `今日締切`, `明日締切`, and `締切未取得`.
- Calendar date cells do not open a separate selected-date event list; switch to `カード` for full event details.

Available filters:

```text
今日以降
今週
今月
締切未取得
すべて
```

Available sort modes:

```text
ライブ日順
申込締切順
```

Available calendar modes:

```text
ライブ日
申込締切
支払期限
すべて
```

The static web app does not call X, Notion, or Google Sheets directly. It only reads `public/events.json`.

`public/events.json` includes both backward-compatible deadline fields and the richer sales-period data:

```text
ticket_application_deadline_at
payment_deadline_at
ticket_sales
next_ticket_deadline_at
next_ticket_sale_type
next_ticket_label
```

The browser sorts `申込締切順` by `next_ticket_deadline_at`, falling back to the older single deadline field when needed.

## Real Tweet Sample Fixtures

While the X API is disabled, manually collected public tweet samples can be added under:

```text
mock_posts/real_samples/
```

Use this JSON format:

```json
{
  "id": "real_sample_001",
  "text": "copied public post text",
  "created_at": "2026-05-30T03:00:00+09:00",
  "url": "https://x.com/info_myojou/status/...",
  "expected_classification": "event | non_event | needs_review",
  "expected_source_kind": "initial_announcement | timetable_update | day_before_reminder | same_day_reminder | ticket_update | correction | sold_out | other",
  "notes": "why this label is expected"
}
```

Manual collection rules:

- Copy the public post text from X.
- Include the public post URL.
- Include `created_at` if visible or infer it carefully from the post timestamp.
- Label `expected_classification` manually.
- Never include private or non-public data.

Evaluate the fixture labels offline:

```bash
.venv/bin/myojou-sync evaluate-real-samples --fixtures mock_posts/real_samples
```

## Validate Environment

Check which sync targets are configured:

```bash
myojou-sync validate-env
```

The command reports each target as available or unavailable and lists missing variables for:

- Notion: `NOTION_TOKEN`, `NOTION_DATABASE_ID`
- Google Sheets: `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`
- both: all Notion and Google Sheets variables
- X: `X_BEARER_TOKEN`

## Notion Setup

1. Create a new Notion database, preferably as a full-page database.
2. Add these public properties exactly as named:

| プロパティ | 推奨タイプ |
| --- | --- |
| イベント名 | title |
| 日付 | date |
| 曜日 | select |
| 会場 | rich_text |
| ライブ情報 | rich_text |
| チケット情報 | rich_text |
| 申込情報 | rich_text |
| 販売期間一覧 | rich_text |
| 次の申込締切 | date |
| 次の販売方式 | select |
| 開場 | rich_text |
| 開演 | rich_text |
| 出演時間 | rich_text |
| 特典会 | rich_text |
| チケットURL | url |
| 一般料金 | number |
| 優先種別 | rich_text |
| 優先料金 | number |
| 当日料金 | number |
| 申込開始 | date |
| 申込締切 | date |
| 当落発表 | date |
| 支払期限 | date |
| 販売方式 | select |
| 販売状況 | select |
| 備考 | rich_text |
| 告知ポスト | url |
| 最終更新 | date |
| 要確認 | checkbox |
| 手動更新 | checkbox |

`日付`, `申込開始`, `申込締切`, `当落発表`, `支払期限`, and `最終更新` should stay Notion `date` properties. Do not make them `rich_text`; date properties are easier to filter with Notion's calendar/date picker UI.

3. For `曜日`, create these select options:

```text
月
火
水
木
金
土
日
```

4. For `販売状況`, create these select options:

```text
未販売
販売中
完売
販売終了
不明
```

If an existing database has `売切` and `終了`, rename them to `完売` and `販売終了`.

5. For `販売方式`, create these select options:

```text
先着
抽選
一般
当日券
無料
不明
```

`販売期間一覧`, `次の申込締切`, and `次の販売方式` are optional but recommended for multiple ticket sales periods. They keep the current single-database Notion setup practical. A separate Ticket Sales database can be added later if commercial requirements need per-ticket history, ownership, or richer reporting.

6. Create these recommended Notion views:

| View | Purpose |
| --- | --- |
| スマホ用：申込・締切 | Smartphone-first application/deadline view |
| 申込・締切 | Avoid missing ticket applications |
| 今後のライブ | Normal fan schedule view |
| 当日・直前 | Live-day quick check |
| 詳細・管理用 | Full table with all properties visible |
| カレンダー | Calendar view using `日付` |
| 要確認 | Review queue filtered to `要確認` checked |

For `スマホ用：申込・締切`:

Purpose: production public view for smartphones. Use Gallery or List, not Table, to avoid horizontal scrolling.

Shown properties:

```text
日付
曜日
会場
ライブ情報
チケット情報
申込情報
チケットURL
販売状況
```

Hidden properties: all detailed raw fields such as `開場`, `開演`, `出演時間`, `特典会`, `一般料金`, `優先料金`, `申込開始`, `申込締切`, `支払期限`, `備考`, `告知ポスト`, `最終更新`, and `手動更新`.

Recommended filter:

```text
日付 is on or after today
```

Use only `日付` for now. Do not filter out empty `申込締切` values; those events should still be visible because `申込情報` will show `未取得`.

Recommended sort:

```text
日付 ascending
開演 ascending
```

For `申込・締切`:

Purpose: main view for avoiding missed ticket applications and deadline checks. 申込締切が空欄のライブも申込・締切ビューに表示する because missing deadline information itself needs to be noticed.

Shown properties:

```text
日付
曜日
イベント名
会場
開演
チケットURL
一般料金
優先料金
販売方式
販売状況
申込開始
申込締切
支払期限
```

Recommended filter:

```text
日付 is on or after today
```

Use only `日付` for now. Do not filter out empty `申込締切` values.

Recommended sort:

```text
日付 ascending
開演 ascending
```

For `今後のライブ`:

Purpose: normal live schedule view.

Shown properties:

```text
日付
曜日
イベント名
会場
開演
出演時間
特典会
チケットURL
一般料金
優先料金
販売状況
```

Recommended filter:

```text
日付 is on or after today
```

Use only `日付` for now.

Recommended sort:

```text
日付 ascending
開演 ascending
```

For `当日・直前`:

Purpose: quick check before or on the live day.

Shown properties:

```text
日付
曜日
イベント名
会場
開演
出演時間
特典会
チケットURL
販売状況
```

Recommended filter:

```text
Use 日付 only, then manually set a range such as today, this week, or the next 7 days in Notion.
```

Recommended sort:

```text
日付 ascending
開演 ascending
```

For `詳細・管理用`:

Purpose: admin/detail view. Keep this as a full table with all properties.

7. Create a Notion integration at <https://www.notion.so/my-integrations>.
8. Copy the integration secret into `.env` as `NOTION_TOKEN`.
9. Share the database with the integration from the Notion database page.
10. Copy the database ID from the Notion database URL into `.env` as `NOTION_DATABASE_ID`.

## Google Sheets Setup

1. Create a new Google Sheet.
2. Rename the first worksheet to the value of `GOOGLE_WORKSHEET_NAME`, or use the default:

```bash
GOOGLE_WORKSHEET_NAME=Live Schedule
```

3. Put this exact Japanese header row in row 1:

```csv
イベント名,日付,曜日,会場,ライブ情報,チケット情報,申込情報,販売期間一覧,次の申込締切,次の販売方式,開場,開演,出演時間,特典会,チケットURL,一般料金,優先種別,優先料金,当日料金,申込開始,申込締切,当落発表,支払期限,販売方式,販売状況,備考,告知ポスト,初回告知URL,最新告知URL,関連告知URL,最新告知日時,最新告知種別,最終更新,要確認,手動更新
```

The sheet remains public-facing, so headers are Japanese. Internal Python and SQLite field names remain English.

4. Create or choose a Google Cloud service account with Sheets access.
5. Download its JSON key and put the whole JSON string in `.env` as `GOOGLE_SERVICE_ACCOUNT_JSON`.
6. Find the service account email in the JSON, usually `client_email`.
7. Share the Google Sheet with that service account email as an editor.
8. Copy the sheet ID from the URL into `.env` as `GOOGLE_SHEET_ID`.

## Preview And Sync Commands

Run tests:

```bash
.venv/bin/pytest
```

Mock dry-run only, with preview:

```bash
.venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-preview.sqlite \
  --dry-run \
  --target none \
  --preview table
```

Mock sync to Notion only:

```bash
DRY_RUN=false .venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-notion.sqlite \
  --no-dry-run \
  --target notion \
  --preview table
```

Mock sync to Google Sheets only:

```bash
DRY_RUN=false .venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-sheets.sqlite \
  --no-dry-run \
  --target sheets \
  --preview table
```

Mock sync to both Notion and Google Sheets:

```bash
DRY_RUN=false .venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-both.sqlite \
  --no-dry-run \
  --target both \
  --preview table
```

Preview-only mode with writes enabled but no external target:

```bash
DRY_RUN=false .venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-none.sqlite \
  --no-dry-run \
  --target none \
  --preview table
```

Real X dry-run without external writes:

```bash
NO_X_API=false .venv/bin/myojou-sync run \
  --no-mock-posts \
  --allow-x-api \
  --db .state/real-x-dry-run.sqlite \
  --max-results 10 \
  --dry-run \
  --target none \
  --preview table
```

JSON preview is also available:

```bash
.venv/bin/myojou-sync run --mock-posts mock_posts --db .state/preview.sqlite --dry-run --preview json
```

Preview output uses the same Japanese labels as Notion and Google Sheets. Weekdays are localized as `月`, `火`, `水`, `木`, `金`, `土`, `日`.

Table preview uses compact smartphone-friendly columns:

```text
日付,曜日,イベント名,会場,ライブ情報,チケット情報,申込情報,チケットURL,要確認
```

JSON preview still includes all public detail fields, including performance time, benefit-event time, same-day ticket price, notes, source URLs, last update fields, and manual override state.

Export the mobile public web JSON from the current SQLite state:

```bash
.venv/bin/myojou-sync export-public \
  --db .state/mock-preview.sqlite \
  --output public/events.json
```

Normal public export filters to `public_ready=true`. Use `--include-not-public-ready` only when investigating parser/backfill quality; do not publish that debug JSON for fans.

Serve the static mobile public web view locally:

```bash
python3 -m http.server 8765 --directory public
```

Then open <http://localhost:8765/>.

Ticket status output is localized:

| Internal value | Public label |
| --- | --- |
| on_sale | 販売中 |
| upcoming | 未販売 |
| sold_out | 完売 |
| same_day | 販売中 |
| ended | 販売終了 |
| unknown | 不明 |

Old or alternate labels are normalized before output:

| Input label | Output label |
| --- | --- |
| 未確認 | 不明 |
| 販売前 | 未販売 |
| 売切 | 完売 |
| 終了 | 販売終了 |
| 当日券あり | 販売中 |

Ticket sale type output is localized:

| Detected text/internal value | Public label |
| --- | --- |
| 先着 / first_come | 先着 |
| 抽選 / lottery | 抽選 |
| 当日券 / same_day | 当日券 |
| 無料 / free | 無料 |
| unknown or missing | 不明 |

## Runtime Safety

The CLI fails clearly when a write target is requested with `DRY_RUN=false` and required environment variables are missing. It silently skips external writes only when dry-run mode is active. `--target none` also skips external writes and is useful for manual inspection.

Sync target behavior:

| Target | Required credentials when `DRY_RUN=false` | Writes |
| --- | --- | --- |
| notion | Notion only | Notion only |
| sheets | Google Sheets only | Google Sheets only |
| both | Notion and Google Sheets | Notion and Google Sheets |
| none | none | none |

If `--target` is omitted and `DRY_RUN=false`, the default target is `both`.

The X username lookup for `@info_myojou` is cached in SQLite under `x_user_id:info_myojou`, so normal runs do not perform username lookup every time. The default `X_MAX_RESULTS` is `10`.

Normal non-backfill real X runs use the stored `last_seen_post_id` as X API `since_id`. Historical backfill mode is separate and does not advance `last_seen_post_id`; use the bootstrap command above when you intentionally want a production DB initialized from saved backfill samples. Check the cursor at any time with:

```bash
.venv/bin/myojou-sync inspect-state --db .state/production.sqlite
```

Logs include:

- posts fetched
- new posts processed
- already processed posts skipped
- non-event posts skipped
- estimated X Post Read count
- X rate-limit headers when available

Mock mode reports `estimated_x_post_reads=0`.

## State And Source Lineage

The SQLite database stores:

- `last_seen_post_id`
- cached X user IDs
- processed source post IDs
- extracted source post records
- canonical event records

Every source post record stores `source_type`, `source_post_id`, `source_url`, `source_posted_at`, `source_text`, `source_kind`, `linked_event_id`, `extraction_confidence`, `classification`, `classification_confidence`, and `classification_reason`.

Posts are classified as:

```text
event
non_event
needs_review
```

Non-event posts are skipped for canonical event creation but preserved in `source_posts` for debugging classifier behavior.

Every canonical event keeps `primary_source_url`, `latest_source_url`, `all_source_urls`, `source_summary`, `last_source_posted_at`, and `last_source_kind`.

## Matching Behavior

Posts are merged into canonical events using event date, normalized event name, normalized venue, normalized ticket URL, and update/reminder keywords such as `タイムテーブル`, `本日`, `明日`, `出演時間`, and `特典会`.

Strong matches are merged. Weak matches set `needs_review=true`. Posts with the same date and venue but clearly different event names or different ticket URLs remain separate events.

When `manual_override=true`, protected fields are not overwritten, but source lineage is still appended.

Protected fields:

```text
event_date
event_name
venue
open_time
start_time
myojou_performance_time
benefit_event_time
ticket_url
general_ticket_price
priority_ticket_name
priority_ticket_price
same_day_ticket_price
ticket_sales
```

Ticket sales are stored as `ticket_sales` periods with sale type, tier/name, price, start, deadline, result, payment deadline, status, and source metadata. The old single deadline fields remain for compatibility and are derived from the next relevant sale period.

## Deployment Options

The current public web view is static, so no VPS or rented server is required at this stage.

The deployable public site is:

```text
public/index.html
public/app.js
public/calendar_helpers.js
public/styles.css
public/events.json
```

All browser paths are relative (`styles.css`, `app.js`, `calendar_helpers.js`, `events.json`), so the demo works under a repository subpath such as `https://USER.github.io/REPO/`.

### GitHub Pages Demo

GitHub Pages is useful for demo and validation because it can host the static `public/` output directly from the repository. Treat it as the demo/testing path, not the long-term commercial hosting choice.

Recommended demo deployment with GitHub Actions:

1. Keep `public/events.json` up to date locally:

   ```bash
   .venv/bin/myojou-sync run \
     --mock-posts mock_posts \
     --db .state/public-web-demo.sqlite \
     --target none \
     --dry-run

   .venv/bin/myojou-sync export-public \
     --db .state/public-web-demo.sqlite \
     --output public/events.json
   ```

2. Commit the generated public files for the demo branch:

   ```text
   public/index.html
   public/app.js
   public/calendar_helpers.js
   public/styles.css
   public/events.json
   ```

3. In GitHub, open the repository settings and enable Pages.
4. Use GitHub Actions as the Pages source and deploy the `public/` directory as the artifact.

Example demo workflow:

```yaml
name: Deploy public demo

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - "public/**"

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: public
      - id: deployment
        uses: actions/deploy-pages@v4
```

Official reference: <https://docs.github.com/en/pages>

### Cloudflare Pages Production Candidate

Cloudflare Pages is the recommended production candidate for the current static app because it is Git-based, serves static assets through Cloudflare's edge network, supports custom domains cleanly, and does not require a VPS or app server for this phase.

Cloudflare Pages setup:

1. Push the repository to GitHub.
2. In Cloudflare, create a Pages project and connect the GitHub repository.
3. Use these build settings:

   ```text
   Framework preset: None
   Build command: None
   Output directory: public
   ```

   If the dashboard requires a build command, use `exit 0`.

4. Deploy.
5. Add a custom domain in Cloudflare Pages.
6. Point the DNS record to the Pages project using Cloudflare's custom domain flow.

Updating `public/events.json`:

- Manual phase: run `myojou-sync export-public --output public/events.json`, commit the changed JSON, and let Cloudflare Pages redeploy from Git.
- Scheduled phase: GitHub Actions can run the sync/export job, update or publish `public/events.json`, and trigger the Pages deployment.

Official reference: <https://developers.cloudflare.com/pages/>

### Vercel Production Alternative

Vercel is a good alternative if the project later moves to React/Vite, serverless endpoints, or a richer frontend workflow.

For the current static app:

```text
Framework preset: Other
Build command: None
Output directory: public
```

If this becomes a commercial project on Vercel, use Pro or a higher plan. Do not use the Hobby plan for commercial use.

Official reference: <https://vercel.com/docs>

### Future Commercial Architecture

Phase 1: static public site plus manually generated `public/events.json`.

Phase 2: GitHub Actions scheduled export from the canonical SQLite/Notion-backed workflow.

Phase 3: Cloudflare Pages production hosting with a custom domain.

Phase 4: Cloudflare Workers API if login, user-specific reminders, dynamic filtering, webhooks, or private data are needed.

Phase 5: paid plan and commercial SaaS architecture with stronger data storage, auth, monitoring, backups, and operational support.

## Future Automation

GitHub Actions can later run scheduled sync/export jobs:

- Fetch recent posts from X.
- Merge into SQLite canonical events.
- Sync the detailed admin database to Notion.
- Export `public/events.json`.
- Publish the `public/` directory to Cloudflare Pages, GitHub Pages demo, or another static host.

## Security Notes

Never commit `.env`, API tokens, Notion tokens, Google service account JSON, or any other secrets.

Store production secrets in GitHub Actions secrets or the hosting provider's environment variable/secrets system:

```text
X_BEARER_TOKEN
NOTION_TOKEN
NOTION_DATABASE_ID
```

Google Sheets secrets can be added later if Sheets sync is started:

```text
GOOGLE_SERVICE_ACCOUNT_JSON
GOOGLE_SHEET_ID
```

`public/events.json` must contain only public fan-facing event data. Do not expose admin-only fields, raw source text, private notes, service account details, Notion tokens, X bearer tokens, or any other secrets in the static site.

## GitHub Actions

Example future workflow for a scheduled Notion sync and public JSON export every 10 minutes:

```yaml
name: Sync myojou live schedule

on:
  schedule:
    - cron: "*/10 * * * *"
  workflow_dispatch:

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - name: Run tests
        run: pytest
      - name: Sync schedule
        env:
          X_BEARER_TOKEN: ${{ secrets.X_BEARER_TOKEN }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
          NO_X_API: "false"
          DRY_RUN: "false"
          X_MAX_RESULTS: "10"
        run: |
          myojou-sync run \
            --no-mock-posts \
            --allow-x-api \
            --db .state/myojou_sync.sqlite \
            --max-results 10 \
            --no-dry-run \
            --target notion
          myojou-sync export-public \
            --db .state/myojou_sync.sqlite \
            --output public/events.json
```

For persistent SQLite state in GitHub Actions, store `.state/myojou_sync.sqlite` in an artifact, cache, or another durable store. Without persistence, each run may refetch recent posts. To publish the fan-facing site, add a GitHub Pages or Cloudflare Pages deployment step that publishes the `public/` directory after `public/events.json` is exported.
