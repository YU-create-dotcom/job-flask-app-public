const SPREADSHEET_ID = '1aripBFJDo9-RkxrDDRfds7YhRZqvPpzjuTZkjJxshmo';
const SHEET_NAME = 'シート1';
const DEFAULT_EVENT_MINUTES = 60;
const REGISTRY_PREFIX = 'JOB_CAL_V2_';
const SOURCE_MARKER = '[job-flask-app:' + SPREADSHEET_ID + ':' + SHEET_NAME + ':';

// Keep the existing entry point. Installation is idempotent and leaves other
// project triggers alone. The timer also catches API edits and retries failures.
function installOnEditTrigger() {
  const spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
  const handlers = new Set(ScriptApp.getProjectTriggers().map(t => t.getHandlerFunction()));
  if (!handlers.has('syncCalendarOnEdit')) {
    ScriptApp.newTrigger('syncCalendarOnEdit').forSpreadsheet(spreadsheet).onEdit().create();
  }
  if (!handlers.has('syncCalendarOnChange')) {
    ScriptApp.newTrigger('syncCalendarOnChange').forSpreadsheet(spreadsheet).onChange().create();
  }
  if (!handlers.has('addInternAndDeadlineEventsToCalendar')) {
    ScriptApp.newTrigger('addInternAndDeadlineEventsToCalendar').timeBased().everyMinutes(15).create();
  }
}

function syncCalendarOnEdit(e) {
  if (!e || !e.range || !e.source || e.source.getId() !== SPREADSHEET_ID) return;
  if (e.range.getSheet().getName() !== SHEET_NAME) return;
  if (e.range.getLastColumn() < 2 || e.range.getColumn() > 11) return;
  addInternAndDeadlineEventsToCalendar();
}

function syncCalendarOnChange(e) {
  if (!e || !e.source || e.source.getId() !== SPREADSHEET_ID) return;
  if (e.changeType === 'FORMAT' || e.changeType === 'EDIT') return;
  addInternAndDeadlineEventsToCalendar();
}

function addInternAndDeadlineEventsToCalendar() {
  return withCalendarLock_(() => reconcileCalendar_());
}

function withCalendarLock_(action) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try { return action(); } finally { lock.releaseLock(); }
}

function readCalendarSource_() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SHEET_NAME);
  if (!sheet) throw new Error('予定シートが見つからないため同期を中止しました。');
  const rows = sheet.getDataRange().getValues();
  // The production sheet has a blank first row and headers on its second row.
  const header = rows.findIndex(row => row[1] === '企業名' && row[6] === 'インターン概要' &&
    row[7] === '締め切り' && row[8] === '参加日(開始時間)' && row[9] === '参加日終了時間');
  if (header < 0) throw new Error('列見出しを確認できないため同期を中止しました。');
  const desired = {};
  const counts = {};
  rows.slice(header + 1).forEach((row, offset) => {
    const company = String(row[1] || '').trim();
    if (!company) return;
    const summary = String(row[6] || '').trim();
    const rowNumber = header + offset + 2;
    const deadline = parseSheetDate_(row[7], rowNumber);
    const start = parseSheetDate_(row[8], rowNumber);
    const end = parseSheetDate_(row[9], rowNumber);
    if (deadline !== null) addDesiredEvent_(desired, counts, company, summary, 'ES締め切り',
      deadline, deadline ? new Date(deadline.getTime() + DEFAULT_EVENT_MINUTES * 60000) : undefined);
    if (start !== null) addDesiredEvent_(desired, counts, company, summary, 'インターン',
      start, !start || end === undefined ? undefined :
        end && end > start ? end : new Date(start.getTime() + DEFAULT_EVENT_MINUTES * 60000));
  });
  return { sheet, rows, desired };
}

function parseSheetDate_(value, rowNumber) {
  if (value === '' || value === null || value === undefined) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (isNaN(date.getTime()) || typeof value === 'number' || typeof value === 'boolean') {
    console.log(rowNumber + '行目の日付が不正です。この予定を保持して他の行の同期を続けます。');
    return undefined;
  }
  return date;
}

function hashCalendarValue_(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, value, Utilities.Charset.UTF_8)
    .map(byte => ('0' + ((byte + 256) % 256).toString(16)).slice(-2)).join('');
}

function buildEventTitle_(company, summary, category) {
  return [company, summary, category].filter(Boolean).join('：');
}

function addDesiredEvent_(desired, counts, company, summary, category, start, end) {
  const title = buildEventTitle_(company, summary, category);
  const description = '・企業名：' + company + '\n・区分：' + category + '\n・インターン概要：' + summary;
  // Content identity survives row insertion, deletion, sorting and moving dates.
  // Identical rows are a multiset; they must not delete each other's events.
  const identity = hashCalendarValue_(JSON.stringify([company, summary, category]));
  counts[identity] = (counts[identity] || 0) + 1;
  const key = identity + '_' + counts[identity];
  desired[key] = start && end ? { title, description, start: start.toISOString(), end: end.toISOString() } :
    { title, description, invalid: true };
}

function managedDescription_(key, record) {
  return record.description + '\n\n' + SOURCE_MARKER + key + ']';
}

function loadRegistry_(props) {
  const records = {};
  const all = props.getProperties();
  Object.keys(all).filter(key => key.startsWith(REGISTRY_PREFIX)).forEach(key => {
    const record = JSON.parse(all[key]); // Corruption must fail closed, never erase history.
    if (!record.calendarId || !record.start || !record.end || !record.description) {
      throw new Error('同期履歴が不正です: ' + key);
    }
    records[key.slice(REGISTRY_PREFIX.length)] = record;
  });
  return records;
}

function saveRecord_(props, records, key, record) {
  props.setProperty(REGISTRY_PREFIX + key, JSON.stringify(record));
  records[key] = record;
}

function resolveRecordedEvent_(calendar, key, record) {
  if (record.calendarId !== calendar.getId()) throw new Error('同期先カレンダーが変わっています。');
  if (record.eventId) return calendar.getEventById(record.eventId);
  // A pending record is written BEFORE creation. Recover a create that succeeded
  // just before a timeout/property-write failure, rather than making a duplicate.
  const matches = calendar.getEvents(new Date(record.start), new Date(record.end))
    .filter(event => event.getDescription() === managedDescription_(key, record));
  if (matches.length > 1) throw new Error('同じ同期IDの予定が複数見つかりました: ' + key);
  return matches[0] || null;
}

function reconcileCalendar_() {
  const source = readCalendarSource_(); // Validate the complete source before any writes.
  const calendar = CalendarApp.getDefaultCalendar();
  const props = PropertiesService.getScriptProperties();
  const records = loadRegistry_(props);
  let created = 0, updated = 0, deleted = 0;
  for (const key of Object.keys(source.desired)) {
    const desired = source.desired[key];
    if (desired.invalid) continue; // Protect an existing ID while this date is being corrected.
    let record = records[key];
    // Claim only explicitly migrated legacy IDs, matching their full content.
    if (!record) {
      const legacyKey = Object.keys(records).find(k => k.startsWith('legacy_') &&
        records[k].description === desired.description && records[k].start === desired.start &&
        records[k].end === desired.end);
      if (legacyKey) {
        record = records[legacyKey];
        saveRecord_(props, records, key, record);
        props.deleteProperty(REGISTRY_PREFIX + legacyKey);
        delete records[legacyKey];
      }
    }
    let event = record ? resolveRecordedEvent_(calendar, key, record) : null;
    if (!event) {
      record = { ...desired, calendarId: calendar.getId(), eventId: null };
      saveRecord_(props, records, key, record);
      event = calendar.createEvent(desired.title, new Date(desired.start), new Date(desired.end),
        { description: managedDescription_(key, desired) });
      // Persist the ID immediately, before any further remote operation.
      record.eventId = event.getId();
      saveRecord_(props, records, key, record);
      created++;
    } else {
      let changed = false;
      if (event.getTitle() !== desired.title) { event.setTitle(desired.title); changed = true; }
      if (event.getDescription() !== managedDescription_(key, desired)) {
        event.setDescription(managedDescription_(key, desired)); changed = true;
      }
      if (event.getStartTime().toISOString() !== desired.start || event.getEndTime().toISOString() !== desired.end) {
        event.setTime(new Date(desired.start), new Date(desired.end)); changed = true;
      }
      if (changed) updated++;
      const next = { ...desired, calendarId: calendar.getId(), eventId: event.getId() };
      if (JSON.stringify(record) !== JSON.stringify(next)) saveRecord_(props, records, key, next);
    }
  }
  // A human can edit while the script lock is held. Never delete against an
  // obsolete snapshot. A subsequent edit/change/timer run will reconcile again.
  if (JSON.stringify(source.rows) !== JSON.stringify(source.sheet.getDataRange().getValues())) {
    throw new Error('同期中にシートが変更されました。次回実行で再同期します。');
  }
  const activeIds = new Set(Object.keys(source.desired).map(key => records[key] && records[key].eventId).filter(Boolean));
  for (const key of Object.keys(records)) {
    if (source.desired[key]) continue;
    const record = records[key];
    // Protect an ID transferred during a migration if a property deletion failed.
    if (!activeIds.has(record.eventId)) {
      const event = resolveRecordedEvent_(calendar, key, record);
      if (event) { event.deleteEvent(); deleted++; }
    }
    // Delete history only AFTER deletion succeeds; retry after API failures.
    props.deleteProperty(REGISTRY_PREFIX + key);
  }
  const result = { desired: Object.keys(source.desired).length, created, updated, deleted };
  console.log(JSON.stringify(result));
  return result;
}

// One-time migration: the old script stored no IDs. Only adopt timed,
// non-recurring events with its exact three-line description AND exact title.
// Preview and review these candidates before running migrateLegacyCalendarEvents.
function getLegacyCalendarCandidates_() {
  const calendar = CalendarApp.getDefaultCalendar();
  const events = calendar.getEvents(new Date('2020-01-01T00:00:00Z'), new Date('2041-01-01T00:00:00Z'));
  return events.filter(event => {
    if (event.isAllDayEvent() || event.isRecurringEvent()) return false;
    const match = /^・企業名：([^\n]+)\n・区分：(ES締め切り|インターン)\n・インターン概要：([^\n]*)$/.exec(event.getDescription());
    if (!match) return false;
    return event.getTitle() === buildEventTitle_(match[1], match[3].trim(), match[2]) ||
      event.getTitle() === buildEventTitle_(match[1], '', match[2]);
  });
}

function previewLegacyCalendarMigration() {
  const desired = Object.values(readCalendarSource_().desired);
  const result = getLegacyCalendarCandidates_().map(event => ({
    title: event.getTitle(), start: event.getStartTime().toISOString(),
    end: event.getEndTime().toISOString(),
    matchesSheet: desired.some(item => item.description === event.getDescription() &&
      item.start === event.getStartTime().toISOString() && item.end === event.getEndTime().toISOString())
  }));
  console.log(JSON.stringify({ candidates: result.length, matching: result.filter(item => item.matchesSheet).length }));
  result.filter(item => !item.matchesSheet).forEach(item => console.log(JSON.stringify(item)));
  return result;
}

function migrateLegacyCalendarEvents() {
  return withCalendarLock_(() => {
    const source = readCalendarSource_();
    const calendar = CalendarApp.getDefaultCalendar();
    const props = PropertiesService.getScriptProperties();
    const records = loadRegistry_(props);
    const knownIds = new Set(Object.values(records).map(record => record.eventId));
    getLegacyCalendarCandidates_().forEach(event => {
      if (knownIds.has(event.getId())) return;
      if (Object.values(source.desired).some(item => item.invalid && item.description === event.getDescription())) return;
      const key = 'legacy_' + hashCalendarValue_(event.getId());
      saveRecord_(props, records, key, {
        calendarId: calendar.getId(), eventId: event.getId(), title: event.getTitle(),
        description: event.getDescription(), start: event.getStartTime().toISOString(),
        end: event.getEndTime().toISOString()
      });
    });
    return reconcileCalendar_();
  });
}
