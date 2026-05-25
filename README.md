# myojou live sync

Python automation for turning recent X posts from `@info_myojou` into one canonical public live schedule. Notion is the primary public database, and Google Sheets is kept in sync as a secondary public view.

Local tests use mock X JSON files only. For the first real Notion/Sheets write, keep using `mock_posts` as input and set `DRY_RUN=false`.

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

`NO_X_API=true` blocks accidental real X fetches unless `--allow-x-api` is passed. `DRY_RUN=true` skips Notion and Google Sheets writes unless `--no-dry-run` is passed.

## Validate Environment

Check which sync targets are configured:

```bash
myojou-sync validate-env
```

The command reports each target as available or unavailable and lists missing variables for:

- Notion: `NOTION_TOKEN`, `NOTION_DATABASE_ID`
- Google Sheets: `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`
- X: `X_BEARER_TOKEN`

## Notion Setup

1. Create a new Notion database, preferably as a full-page database.
2. Add these public properties exactly as named:

| Property | Recommended type |
| --- | --- |
| event_date | date |
| weekday | rich_text |
| event_name | title |
| venue | rich_text |
| open_time | rich_text |
| start_time | rich_text |
| myojou_performance_time | rich_text |
| benefit_event_time | rich_text |
| ticket_url | url |
| general_ticket_price | number |
| priority_ticket_name | rich_text |
| priority_ticket_price | number |
| same_day_ticket_price | number |
| ticket_status | select |
| notes | rich_text |
| source_summary | rich_text |
| primary_source_url | url |
| latest_source_url | url |
| all_source_urls | rich_text |
| last_updated_at | date |
| needs_review | checkbox |
| manual_override | checkbox |

3. Add one internal sync property:

| Property | Recommended type |
| --- | --- |
| event_id | rich_text |

The sync uses `event_id` for stable upserts. You can hide it from the public view.

4. Create a Notion integration at <https://www.notion.so/my-integrations>.
5. Copy the integration secret into `.env` as `NOTION_TOKEN`.
6. Share the database with the integration from the Notion database page.
7. Copy the database ID from the Notion database URL into `.env` as `NOTION_DATABASE_ID`.

## Google Sheets Setup

1. Create a new Google Sheet.
2. Rename the first worksheet to the value of `GOOGLE_WORKSHEET_NAME`, or use the default:

```bash
GOOGLE_WORKSHEET_NAME=Live Schedule
```

3. Put this exact header row in row 1:

```csv
event_id,event_date,weekday,event_name,venue,open_time,start_time,myojou_performance_time,benefit_event_time,ticket_url,general_ticket_price,priority_ticket_name,priority_ticket_price,same_day_ticket_price,ticket_status,notes,source_summary,primary_source_url,latest_source_url,all_source_urls,last_updated_at,needs_review,manual_override
```

`event_id` is internal and lets the sync update existing rows instead of appending duplicates.

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
  --preview table
```

Mock sync to Notion only:

```bash
DRY_RUN=false .venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-notion.sqlite \
  --no-dry-run \
  --sync-notion \
  --preview table
```

Mock sync to Google Sheets only:

```bash
DRY_RUN=false .venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-sheets.sqlite \
  --no-dry-run \
  --sync-sheets \
  --preview table
```

Mock sync to both Notion and Google Sheets:

```bash
DRY_RUN=false .venv/bin/myojou-sync run \
  --mock-posts mock_posts \
  --db .state/mock-both.sqlite \
  --no-dry-run \
  --sync-notion \
  --sync-sheets \
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
  --preview table
```

JSON preview is also available:

```bash
.venv/bin/myojou-sync run --mock-posts mock_posts --db .state/preview.sqlite --dry-run --preview json
```

## Runtime Safety

The CLI fails clearly when a write target is requested with `DRY_RUN=false` and required environment variables are missing. It silently skips external writes only when dry-run mode is active.

The X username lookup for `@info_myojou` is cached in SQLite under `x_user_id:info_myojou`, so normal runs do not perform username lookup every time. The default `X_MAX_RESULTS` is `10`.

Logs include:

- posts fetched
- new posts processed
- already processed posts skipped
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

Every source post record stores `source_type`, `source_post_id`, `source_url`, `source_posted_at`, `source_text`, `source_kind`, `linked_event_id`, and `extraction_confidence`.

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
```

## GitHub Actions

Example workflow for a scheduled full sync every 10 minutes:

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
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
          GOOGLE_SHEET_ID: ${{ secrets.GOOGLE_SHEET_ID }}
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
            --sync-notion \
            --sync-sheets
```

For persistent SQLite state in GitHub Actions, store `.state/myojou_sync.sqlite` in an artifact, cache, or another durable store. Without persistence, each run may refetch recent posts.
