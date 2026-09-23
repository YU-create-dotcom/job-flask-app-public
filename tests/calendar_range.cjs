const assert = require('node:assert/strict');
const { eventOccursOnDate: occurs } = require('../static/calendar-range.js');
const tests = [
    ['single day deadline', {date:'2026-09-14'}, ['2026-09-14'], ['2026-09-13','2026-09-15']],
    ['three days', {date:'2026-09-14',end_date:'2026-09-16',end_time:'18:00'}, ['2026-09-14','2026-09-15','2026-09-16'], ['2026-09-13','2026-09-17']],
    ['month boundary', {date:'2026-09-30',end_date:'2026-10-02',end_time:'18:00'}, ['2026-09-30','2026-10-01','2026-10-02'], ['2026-09-29','2026-10-03']],
    ['year boundary', {date:'2026-12-31',end_date:'2027-01-02',end_time:'18:00'}, ['2026-12-31','2027-01-01','2027-01-02'], ['2026-12-30','2027-01-03']],
    ['midnight exclusive', {date:'2026-09-14',end_date:'2026-09-16',end_time:'00:00'}, ['2026-09-14','2026-09-15'], ['2026-09-16']],
    ['date only inclusive', {date:'2026-09-14',end_date:'2026-09-16'}, ['2026-09-14','2026-09-15','2026-09-16'], ['2026-09-17']],
    ['same day midnight', {date:'2026-09-14',end_date:'2026-09-14',end_time:'00:00'}, ['2026-09-14'], ['2026-09-15']],
    ['invalid end fallback', {date:'2026-09-14',end_date:'2026-09-13'}, ['2026-09-14'], ['2026-09-13','2026-09-15']],
    ['leap day', {date:'2028-02-28',end_date:'2028-03-01',end_time:'18:00'}, ['2028-02-28','2028-02-29','2028-03-01'], ['2028-03-02']]
];
for (const [name,event,yes,no] of tests) {
    for (const date of yes) assert.equal(occurs(event,date),true,`${name}: ${date}`);
    for (const date of no) assert.equal(occurs(event,date),false,`${name}: ${date}`);
}
console.log(`${tests.length} calendar date-range cases passed`);
