const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const source = fs.readFileSync(process.argv[2] || `${__dirname}/../gas/calendar_sync.gs`, 'utf8');
const ID = '1aripBFJDo9-RkxrDDRfds7YhRZqvPpzjuTZkjJxshmo';
const header = ['', '企業名', '', '', '', '', 'インターン概要', '締め切り', '参加日(開始時間)', '参加日終了時間'];
const row = (company='A社',start='2026-09-14T09:00:00+09:00',end='2026-09-16T18:00:00+09:00') =>
    ['',company,'',false,'','','3days','',start,end];
function harness() {
    let rows = [[],header,row()], nextId = 1, readCount = 0;
    const properties = {}, events = new Map(), triggers = [];
    const state = {failCreate:false,failSaveId:false,failDelete:false,changeOnReread:false};
    const props = {
        getProperties:()=>({...properties}),
        setProperty:(key,value)=>{
            if(state.failSaveId && JSON.parse(value).eventId) {state.failSaveId=false; throw Error('save failed');}
            properties[key]=value;
        },
        deleteProperty:key=>{delete properties[key];}
    };
    const createEvent = (title,start,end,options={}) => {
        if(state.failCreate) throw Error('create failed');
        const id = `event-${nextId++}`;
        const event = {
            id,title,start,end,description:options.description || '',deleted:false,
            getId(){return id;}, getTitle(){return this.title;}, getDescription(){return this.description;},
            getStartTime(){return this.start;},getEndTime(){return this.end;},
            setTitle(v){this.title=v;},setDescription(v){this.description=v;},setTime(s,e){this.start=s;this.end=e;},
            isAllDayEvent(){return false;},isRecurringEvent(){return false;},
            deleteEvent(){if(state.failDelete) throw Error('delete failed'); this.deleted=true;}
        };
        events.set(id,event); return event;
    };
    const calendar = {
        getId:()=> 'calendar-1',createEvent,
        getEventById:id=>events.get(id)?.deleted ? null : events.get(id) || null,
        getEvents:(start,end)=>[...events.values()].filter(e=>!e.deleted && e.start<end && e.end>start)
    };
    const sheet = {getName:()=> 'シート1',getDataRange:()=>({getValues:()=>{
        readCount++;
        if(state.changeOnReread && readCount % 2 === 0) return [[],header,row('changed')];
        return rows.map(r=>[...r]);
    }})};
    const spreadsheet = {getId:()=>ID,getSheetByName:()=>sheet};
    const context = vm.createContext({
        Date,console:{log:()=>{}},
        SpreadsheetApp:{openById:()=>spreadsheet},CalendarApp:{getDefaultCalendar:()=>calendar},
        PropertiesService:{getScriptProperties:()=>props},
        LockService:{getScriptLock:()=>({waitLock(){},releaseLock(){}})},
        Utilities:{DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},
            computeDigest:(_,value)=>[...crypto.createHash('sha256').update(value).digest()]},
        ScriptApp:{getProjectTriggers:()=>triggers,newTrigger:handler=>{
            const builder={forSpreadsheet(){return builder;},onEdit(){return builder;},onChange(){return builder;},
                timeBased(){return builder;},everyMinutes(){return builder;},create(){triggers.push({getHandlerFunction:()=>handler});}};
            return builder;
        }}
    });
    vm.runInContext(source,context);
    return {context,state,events,properties,calendar,spreadsheet,triggers,
        setRows:r=>{rows=[[],header,...r];readCount=0;},setRaw:r=>{rows=r;readCount=0;},
        sync:()=>context.addInternAndDeadlineEventsToCalendar(),
        live:()=>[...events.values()].filter(e=>!e.deleted)};
}
const tests = {
    'creation and repeat keeps one persistent ID'(){const h=harness();h.sync();const id=h.live()[0].id;h.sync();assert.equal(h.live().length,1);assert.equal(h.live()[0].id,id);},
    'multi-day end is retained'(){const h=harness();h.sync();assert.equal(h.live()[0].end.toISOString(),'2026-09-16T09:00:00.000Z');},
    'date edit updates same ID'(){const h=harness();h.sync();const id=h.live()[0].id;h.setRows([row('A社','2026-10-01T09:00:00+09:00','2026-10-03T18:00:00+09:00')]);h.sync();assert.equal(h.live()[0].id,id);assert.equal(h.live()[0].start.toISOString(),'2026-10-01T00:00:00.000Z');},
    'row deletion also works when sheet becomes empty'(){const h=harness();h.sync();h.setRows([]);h.sync();assert.equal(h.live().length,0);assert.equal(Object.keys(h.properties).length,0);},
    'clearing company deletes managed event'(){const h=harness();h.sync();h.setRows([row('')]);h.sync();assert.equal(h.live().length,0);},
    'clearing date deletes managed event'(){const h=harness();h.sync();h.setRows([row('A社','','')]);h.sync();assert.equal(h.live().length,0);},
    'deadline independent from internship'(){const h=harness();const r=row();r[7]='2026-09-10T00:00:00+09:00';h.setRows([r]);h.sync();assert.equal(h.live().length,2);r[7]='';h.setRows([r]);h.sync();assert.equal(h.live().length,1);assert.match(h.live()[0].title,/インターン/);},
    'sorting and inserting blank rows keeps IDs'(){const h=harness();h.setRows([row(),row('B社')]);h.sync();const ids=h.live().map(e=>e.id);h.setRows([row('B社'),[],row()]);h.sync();assert.deepEqual(h.live().map(e=>e.id),ids);},
    'identical rows do not destroy each other'(){const h=harness();h.setRows([row(),row()]);h.sync();assert.equal(h.live().length,2);h.setRows([row()]);h.sync();assert.equal(h.live().length,1);},
    'manual unrelated event with same title is preserved'(){const h=harness();h.calendar.createEvent('A社：3days：インターン',new Date('2026-09-14'),new Date('2026-09-15'),{description:'personal'});h.sync();h.setRows([]);h.sync();assert.equal(h.live().length,1);assert.equal(h.live()[0].description,'personal');},
    'invalid date protects that event while other rows synchronize'(){const h=harness();h.sync();const id=h.live()[0].id;h.setRows([row('A社','invalid'),row('B社')]);h.sync();assert.equal(h.live().length,2);assert.ok(h.live().some(e=>e.id===id));},
    'invalid date in unrelated existing row does not block deletion'(){const h=harness();h.sync();h.setRows([row('B社',']')]);h.sync();assert.equal(h.live().length,0);},
    'missing header stops deletions'(){const h=harness();h.sync();h.setRaw([]);assert.throws(h.sync,/列見出し/);assert.equal(h.live().length,1);},
    'creation failure retains existing events'(){const h=harness();h.sync();h.setRows([row('B社')]);h.state.failCreate=true;assert.throws(h.sync,/create failed/);assert.equal(h.live().length,1);},
    'failed ID write recovers without duplication'(){const h=harness();h.state.failSaveId=true;assert.throws(h.sync,/save failed/);assert.equal(h.live().length,1);h.sync();assert.equal(h.live().length,1);assert.ok(Object.values(h.properties).every(v=>JSON.parse(v).eventId));},
    'pending creation can be removed after row deletion'(){const h=harness();h.state.failSaveId=true;assert.throws(h.sync);h.setRows([]);h.sync();assert.equal(h.live().length,0);},
    'failed deletion retains ID and retries'(){const h=harness();h.sync();h.setRows([]);h.state.failDelete=true;assert.throws(h.sync,/delete failed/);assert.equal(Object.keys(h.properties).length,1);h.state.failDelete=false;h.sync();assert.equal(h.live().length,0);},
    'concurrent sheet edit stops deletion'(){const h=harness();h.sync();h.setRows([]);h.state.changeOnReread=true;assert.throws(h.sync,/シートが変更/);assert.equal(h.live().length,1);},
    'legacy migration adopts exact generated events and removes orphans'(){
        const h=harness();const old=h.calendar.createEvent('A社：3days：インターン',new Date('2026-09-14T09:00:00+09:00'),new Date('2026-09-16T18:00:00+09:00'),{description:'・企業名：A社\n・区分：インターン\n・インターン概要：3days'});
        h.calendar.createEvent('削除済み：インターン',new Date('2026-08-01'),new Date('2026-08-02'),{description:'・企業名：削除済み\n・区分：インターン\n・インターン概要：'});
        h.calendar.createEvent('manual',new Date('2026-08-01'),new Date('2026-08-02'),{description:'・企業名：A社\n・区分：インターン\n・インターン概要：3days'});
        assert.equal(h.context.previewLegacyCalendarMigration().length,2);
        h.context.migrateLegacyCalendarEvents();assert.equal(h.live().length,2);assert.ok(h.live().some(e=>e.id===old.id));h.context.migrateLegacyCalendarEvents();assert.equal(h.live().length,2);
    },
    'trigger installation is idempotent'(){const h=harness();h.context.installOnEditTrigger();h.context.installOnEditTrigger();assert.equal(h.triggers.length,3);},
    'row removal change event invokes sync'(){const h=harness();h.sync();h.setRows([]);h.context.syncCalendarOnChange({source:h.spreadsheet,changeType:'REMOVE_ROW'});assert.equal(h.live().length,0);}
};
for(const [name,test] of Object.entries(tests)){test();console.log(`PASS ${name}`);}
console.log(`${Object.keys(tests).length} synchronization cases passed`);
