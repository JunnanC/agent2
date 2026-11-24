import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { TeacherIcon, TeacherScrollFrame } from "./teacher-b";

const weekdays = ["一", "二", "三", "四", "五", "六", "日"];
const dayMs = 86_400_000;
const iso = (date: Date) => date.toISOString().slice(0, 10);
const dateOf = (day: string) => new Date(day + "T00:00:00Z");
const advance = (date: Date, days: number) => new Date(date.getTime() + days * dayMs);
const monthText = (date: Date) => `${date.getUTCFullYear()} 年 ${date.getUTCMonth() + 1} 月`;
const shortDate = (date: Date) => `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;

export interface AgendaTerm {
  id: string;
  label: string;
  calendar?: { start: string; weeks: number; defaultWeek: number; currentWeek?: number };
}

export interface AgendaClass {
  id: string;
  title: string;
  lessonTitle?: string;
  group?: string;
  students?: number;
  experiments?: number;
}

export interface AgendaSlot {
  id: string;
  course: AgendaClass;
  weekday: number;
  start: number;
  end: number;
  classroom: string;
  weekStart: number | null;
  weekEnd: number | null;
  parity: "ALL" | "ODD" | "EVEN";
}

export interface AgendaTodo { href: string; label: string; meta: string; count: string; key: string }
export interface AgendaPeriod { start: number; end: number; time?: string }

function periodText(start: number, end: number) {
  return start === end ? String(start) : `${start}–${end}`;
}

function inWeek(slot: AgendaSlot, week: number | undefined) {
  if (week == null) return true;
  return (slot.weekStart == null || week >= slot.weekStart) &&
    (slot.weekEnd == null || week <= slot.weekEnd) &&
    (slot.parity === "ALL" || (week % 2 === 0 ? slot.parity === "EVEN" : slot.parity === "ODD"));
}

function conditions(slot: AgendaSlot) {
  const range = slot.weekStart != null && slot.weekEnd != null ? `第 ${periodText(slot.weekStart, slot.weekEnd)} 周`
    : slot.weekStart != null ? `第 ${slot.weekStart} 周起` : slot.weekEnd != null ? `截至第 ${slot.weekEnd} 周` : "";
  return [range, slot.parity === "ODD" ? "单周" : slot.parity === "EVEN" ? "双周" : ""].filter(Boolean).join(" · ");
}

function MonthCalendar({ selected, first, last, offset, onMonth, onDay }: {
  selected: Date; first: Date; last: Date; offset: number; onMonth: (offset: number) => void; onDay: (date: Date) => void;
}) {
  const month = new Date(Date.UTC(selected.getUTCFullYear(), selected.getUTCMonth() + offset, 1));
  const end = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 0));
  return <section className="mini-month" aria-label="按日期查看授课">
    <div className="month-label"><h2>{monthText(month)}</h2><div className="month-pager">
      <button type="button" aria-label="上月" disabled={month <= first} onClick={() => onMonth(offset - 1)}><TeacherIcon name="left" /></button>
      <button type="button" aria-label="下月" disabled={end >= last} onClick={() => onMonth(offset + 1)}><TeacherIcon name="right" /></button>
    </div></div>
    <div className="month-grid">{weekdays.map((label) => <span key={label} className="weekday">{label}</span>)}
      {Array.from({ length: end.getUTCDate() }, (_, index) => {
        const date = advance(month, index);
        return <button key={index} type="button" aria-label={iso(date)} aria-pressed={iso(date) === iso(selected)}
          style={index === 0 ? { gridColumn: (month.getUTCDay() + 6) % 7 + 1 } : undefined}
          disabled={date < first || date > last} onClick={() => onDay(date)}>{index + 1}</button>;
      })}
    </div>
  </section>;
}

function useAgendaWeek(term: AgendaTerm) {
  const [weeks, setWeeks] = useState<Record<string, number>>({});
  const week = weeks[term.id] ?? term.calendar?.defaultWeek;
  const setWeek = (value: number) => setWeeks((previous) => ({ ...previous, [term.id]: value }));
  return { week, setWeek };
}

function WeekButtons({ term, week, onWeek }: { term: AgendaTerm; week: number | undefined; onWeek: (value: number) => void }) {
  if (week == null || !term.calendar) return null;
  const { currentWeek, weeks } = term.calendar;
  return <div className="week"><div className="week-step" role="group" aria-label="切换教学周">
    <button type="button" className="btn square" aria-label="上一周" disabled={week <= 1} onClick={() => onWeek(week - 1)}><TeacherIcon name="left" /></button>
    <span>第 {week} 周</span>
    <button type="button" className="btn square" aria-label="下一周" disabled={week >= weeks} onClick={() => onWeek(week + 1)}><TeacherIcon name="right" /></button>
  </div>{currentWeek != null && <button type="button" className="btn jump-week" disabled={week === currentWeek} onClick={() => onWeek(currentWeek)}>本周</button>}</div>;
}

export function AgendaWeek({ title = "教学课表", term, week, slots, classes, periods = [], today, controls }: {
  title?: string; term: AgendaTerm; week?: number; slots: AgendaSlot[]; classes: AgendaClass[];
  periods?: AgendaPeriod[]; today: string; controls: ReactNode;
}) {
  const weekStart = term.calendar && week != null ? advance(dateOf(term.calendar.start), (week - 1) * 7) : null;
  const rows = [...new Map([...periods, ...slots.map(({ start, end }) => ({ start, end }))].reverse()
    .map((period) => [periodText(period.start, period.end), period])).values()].sort((a, b) => a.start - b.start || a.end - b.end) as AgendaPeriod[];
  const sessions = slots.filter((slot) => inWeek(slot, week));
  const days = weekdays.slice(0, Math.max(5, ...slots.map((slot) => slot.weekday + 1))).map((name, index) => {
    const date = weekStart ? advance(weekStart, index) : null;
    return { label: `周${name}`, date, today: date != null && iso(date) === today };
  });
  const tone = (course: AgendaClass) => ["blue", "teal", "slate"][classes.findIndex(({ id }) => id === course.id) % 3] ?? "blue";
  return <section className="panel agenda-panel schedule">
    <div className="panel-head"><div><h2>{title}</h2><p className="small">{weekStart ? `${shortDate(weekStart)} – ${shortDate(advance(weekStart, 6))} · 共 ${sessions.length} 次课` : `常规排课 · 共 ${sessions.length} 个时段`}</p></div>{controls}</div>
    {sessions.length ? <><TeacherScrollFrame label="周课表">
      <div className={`timetable${days.length > 5 ? " extended-week" : ""}`} style={{ "--week-days": days.length } as React.CSSProperties}>
        <div className="tt-cell tt-label day first-period">节次</div>
        {days.map((day) => <div key={day.label} className={`tt-cell tt-label day ${day.today ? "today" : ""}`} aria-current={day.today ? "date" : undefined}>
          <strong>{day.label}</strong>{day.date && <span className="date">{shortDate(day.date)}</span>}
        </div>)}
        {rows.map((period) => <Fragment key={periodText(period.start, period.end)}>
          <div className="tt-cell tt-label first-period">{periodText(period.start, period.end)} 节{period.time && <span className="date">{period.time}</span>}</div>
          {days.map((day, index) => <div key={day.label} className={`tt-cell${day.today ? " today-column" : ""}`}>
            {sessions.filter((slot) => slot.weekday === index && slot.start === period.start && slot.end === period.end).map((slot) => {
              const detail = [slot.course.group, slot.classroom, week == null && conditions(slot)].filter(Boolean).join(" · ");
              return <Link key={slot.id} className="slot" to={`/courses/${slot.course.id}`} data-tone={tone(slot.course)}
                aria-label={`${slot.course.title}，${day.label}，第 ${periodText(slot.start, slot.end)} 节${detail ? `，${detail}` : ""}`}>
                <strong>{slot.course.lessonTitle ?? slot.course.title}</strong><span className="slot-full">{detail}</span>
                <span className="slot-compact">{slot.course.group}{slot.course.group && slot.classroom && <br />}{slot.classroom.split(" ").at(-1)}{week == null && conditions(slot) && <><br />{conditions(slot)}</>}</span>
              </Link>;
            })}
          </div>)}
        </Fragment>)}
      </div></TeacherScrollFrame><div className="legend small">{classes.filter((course) => sessions.some((slot) => slot.course.id === course.id))
        .map((course) => <span key={course.id}><i className="swatch" data-tone={tone(course)} />{course.title}</span>)}</div></>
      : <p className="empty">{slots.length ? "所选教学周没有排课。" : "本学期还没有排课。"}</p>}
  </section>;
}

export function ClassAgendaWeek(props: { term: AgendaTerm; slots: AgendaSlot[]; classes: AgendaClass[]; today: string }) {
  const { week, setWeek } = useAgendaWeek(props.term);
  return <AgendaWeek {...props} title="班级课表" week={week} controls={<WeekButtons term={props.term} week={week} onWeek={setWeek} />} />;
}

export function TeachingAgenda({ term, terms, classes, slots, todos, today, periods = [], onTerm, onImport, onEnvironments,
  classActions, scheduleState, classesState, todosState }: {
  term: AgendaTerm; terms: AgendaTerm[]; classes: AgendaClass[]; slots: AgendaSlot[]; todos: AgendaTodo[]; today: string;
  periods?: AgendaPeriod[]; onTerm: (id: string) => void; onImport: () => void; onEnvironments: () => void;
  classActions?: ReactNode; scheduleState?: ReactNode; classesState?: ReactNode; todosState?: ReactNode;
}) {
  const { week, setWeek } = useAgendaWeek(term);
  const [weekday, setWeekday] = useState((dateOf(today).getUTCDay() + 6) % 7);
  const [view, setView] = useState<"day" | "week">("day");
  const [month, setMonth] = useState({ termId: term.id, offset: 0 });
  const offset = month.termId === term.id ? month.offset : 0;
  const setOffset = (value: number) => setMonth({ termId: term.id, offset: value });
  const first = term.calendar ? dateOf(term.calendar.start) : null;
  const firstDay = first && week != null ? advance(first, (week - 1) * 7) : null;
  const selected = firstDay ? advance(firstDay, weekday) : null;

  function chooseDay(index: number, date?: Date) {
    setWeekday(index);
    if (date && first) setWeek(Math.floor((date.getTime() - first.getTime()) / (7 * dayMs)) + 1);
    setOffset(0);
    setView("day");
  }

  const picker = (className: string) => <div className={className} role="group" aria-label="选择授课日期">
    {weekdays.map((name, index) => {
      const date = firstDay ? advance(firstDay, index) : null;
      return <button key={index} type="button" aria-label={date ? iso(date) : `星期${name}`} aria-pressed={weekday === index} onClick={() => chooseDay(index)}>
        <span>周{name}</span>{date && <strong>{date.getUTCDate()}</strong>}
      </button>;
    })}
  </div>;
  const weekControls = <WeekButtons term={term} week={week} onWeek={(value) => { setWeek(value); setOffset(0); }} />;
  const lessons = slots.filter((slot) => slot.weekday === weekday && inWeek(slot, week))
    .sort((a, b) => a.start - b.start || a.end - b.end);
  return <>
    <header className="page-heading"><h1>教学日程</h1><div className="heading-actions">
      <select aria-label="学期" value={term.id} disabled={!terms.length} onChange={(event) => { setOffset(0); onTerm(event.target.value); }}>
        {!terms.length && <option value={term.id}>{term.label}</option>}
        {terms.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
      </select>
      <button type="button" className="btn" onClick={onEnvironments}><TeacherIcon name="terminal" />实验环境</button>
      <button type="button" className="btn primary" disabled={!term.id} onClick={onImport}><TeacherIcon name="upload" />导入课表</button>
    </div></header>
    <div className="journal"><aside className="journal-aside">
      {selected && first && term.calendar ? <MonthCalendar selected={selected} first={first} last={advance(first, term.calendar.weeks * 7 - 1)}
        offset={offset} onMonth={setOffset} onDay={(date) => chooseDay((date.getUTCDay() + 6) % 7, date)} />
        : <section className="mini-month"><div className="month-label"><h2>按星期查看</h2></div>{picker("weekday-picker")}</section>}
      <section className="term-classes"><div className="aside-heading"><h2>我的教学班</h2><span className="small">{classes.length} 个班</span></div>
        {classesState}{classes.length ? <ul className="class-index">{classes.map((course) => <li key={course.id}>
          <Link to={`/courses/${course.id}`}><span><strong>{course.title}</strong>
            <small className="small">{course.students ?? "—"} 名学生 · {course.experiments ?? "—"} 个实验</small></span><TeacherIcon name="right" /></Link>
        </li>)}</ul> : !classesState && <p className="empty">本学期暂无教学班。</p>}
        {classActions}
      </section>
    </aside><div className="folio">
      <div className="folio-top">
        {selected ? <time className="folio-date" dateTime={iso(selected)}><strong className="day-number">{selected.getUTCDate()}</strong>
          <span className="date-detail"><strong>星期{weekdays[weekday]}</strong><span>{monthText(selected)}</span></span></time>
          : <div className="date-detail"><strong>星期{weekdays[weekday]}</strong><span>缺少校历，暂按星期和节次查看</span></div>}
        <div role="group" aria-label="课表视图" className="view-switch">
          <button type="button" aria-pressed={view === "day"} onClick={() => setView("day")}>日程</button>
          <button type="button" aria-pressed={view === "week"} onClick={() => setView("week")}>周课表</button>
        </div>
      </div>
      {scheduleState}
      {view === "day" ? <>{picker("mobile-days")}<section><div className="journal-heading"><h2>{selected ? "当日课程" : "本日常规排课"}</h2>{weekControls}</div>
        {lessons.length ? <ol className="day-lessons">{lessons.map((slot) => {
          const periodsText = `第 ${periodText(slot.start, slot.end)} 节`;
          const clock = periods.find((period) => period.start === slot.start && period.end === slot.end)?.time;
          return <li key={slot.id}><Link className="lesson" to={`/courses/${slot.course.id}`}>
            <span className="lesson-clock"><strong>{clock ?? periodsText}</strong>{clock && <small>{periodsText}</small>}</span>
            <span className="lesson-details"><strong>{slot.course.lessonTitle ?? slot.course.title}</strong>
              <span>{[slot.course.group, slot.classroom, week == null && conditions(slot)].filter(Boolean).join(" · ")}</span></span><TeacherIcon name="right" />
          </Link></li>;
        })}</ol> : !scheduleState && <p className="empty">这一天没有排课。</p>}
      </section></> : <AgendaWeek term={term} week={week} slots={slots} classes={classes} periods={periods} today={today} controls={weekControls} />}
      <section className="pending"><div className="journal-heading"><h2>教学待办</h2></div>{todosState}
        {todos.length ? <ul className="work-list">{todos.map((item) => <li key={item.key}><Link className="work-row" to={item.href}>
          <span><strong>{item.label}</strong><span className="small">{item.meta}</span></span><span className="count">{item.count}</span>
        </Link></li>)}</ul> : !todosState && <p className="empty">本学期暂无待处理事项。</p>}
      </section>
    </div></div>
  </>;
}
