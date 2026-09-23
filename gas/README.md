# Calendar synchronization

`calendar_sync.gs` is the source for the existing **カレンダー連携** Apps Script project:
https://script.google.com/home/projects/1mO6dGcFxnjY-spBksxfstkWRL8zyVk1W-TZqIaP4VuNcDNNGDnx4qHcL/edit

The separately linked **メール管理** project imports email and is unchanged.
Render deploys the Flask site; it does not deploy Apps Script. Paste this file into
the calendar project's `コード.gs` and save, then verify the pasted content.

## Behavior

- `syncCalendarOnEdit` retains the original edit trigger entry point.
- `syncCalendarOnChange` reconciles row removals and other structural changes.
- `addInternAndDeadlineEventsToCalendar` reconciles the full sheet and runs every
  15 minutes as a retry and to catch changes made by APIs or other scripts.
- `installOnEditTrigger` installs only missing handlers and preserves unrelated triggers.
- The original default calendar, event titles, descriptions, one-hour fallback,
  deadline handling and timed start/end semantics are retained.
- The site displays a timed event on each date it occupies, including across
  month/year boundaries. A midnight end is exclusive. Desktop and mobile use the
  same predicate. API events are not duplicated, so dashboard counts stay unchanged.

## Persistent ownership and failure handling

Script Properties with prefix `JOB_CAL_V2_` retain the calendar ID and event ID
independently of the sheet. Identity uses company, summary, category and duplicate
occurrence count; moving a date updates its existing ID. Sorting/inserting/removing
rows does not invalidate ownership. Changing company/summary replaces the managed
event. Duplicate identical rows are represented separately.

Only recorded IDs can be deleted during normal reconciliation; matching a company
name or title never grants ownership. A pending record is written before creating
an event, and an exact source marker in the description recovers a creation if the
ID write fails. Deletion failures retain the ID for retry. A script lock prevents
overlapping executions. The source is reread before deleting; source-read errors,
missing headers/sheets or a concurrent edit stop deletion. Invalid nonempty date
cells preserve that event and log the row number while valid rows continue syncing.
Blank company/start cells remove the corresponding managed events.

Do not clear Script Properties during routine maintenance. They are the ownership
registry, including events whose source rows have already been removed. Calendar
or property API errors must not be caught and treated as empty data. The registry
uses one property per event; monitor Apps Script property/service quotas as the
sheet grows. History is removed when deletion succeeds.

## One-time migration from the previous script

1. Run `previewLegacyCalendarMigration` and inspect the unmatched candidates.
2. Run `migrateLegacyCalendarEvents` once after reviewing those candidates.
3. Run normal synchronization again; it should report zero creations/updates/deletions.
4. Run `installOnEditTrigger` and confirm edit, change and 15-minute triggers exist.

The old script stored no IDs or source tags. Migration recognizes only non-recurring,
timed events with its exact three-line description and exact current/legacy title.
It searches **2020-01-01 through 2040-12-31**. Events outside this range, manually
modified descriptions, all-day and recurring events require separate review and
are not swept automatically. This strict signature is a migration heuristic, so
preview it; after migration all deletion uses recorded IDs. Do not broaden migration
to company/title-only matching. Invalid-date source entries are not migrated until
corrected. No new calendar or spreadsheet permissions are required.

## Regression tests

Run from the repository root with Node.js:

```
node tests/calendar_range.cjs
node tests/calendar_sync.cjs
```

The synchronization tests use in-memory Apps Script/Calendar/Sheets doubles; they
do not write to Google. They cover deletion, clearing cells, duplicate rows,
date changes, retry recovery, concurrent edits, migration and unrelated events.

Google references:
- https://developers.google.com/apps-script/guides/triggers/installable
- https://developers.google.com/apps-script/guides/triggers/events
- https://developers.google.com/apps-script/reference/calendar/calendar
