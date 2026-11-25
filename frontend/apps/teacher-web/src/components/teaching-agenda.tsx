import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { TimetableCalendar } from "@edu/api-client";
import { TeacherIcon, TeacherScrollFrame } from "./teacher-b";

const weekdays = ["一", "二", "三", "四", "五", "六", "日"];
const dayMs = 86_400_000;
const iso = (date: Date) => date.toISOString().slice(0, 10);
const dateOf = (day: string) => new Date(day + "T00:00:00Z");
const advance = (date: Date, days: number) => new Date(date.getTime() + days * dayMs);
const weekdayOf = (date: Date) => (date.getUTCDay() + 6) % 7;
const mondayOf = (date: Date) => advance(date, -weekdayOf(date));
const monthText = (date: Date) => `${date.getUTCFullYear()} 年 ${date.getUTCMonth() + 1} 月`;
const shortDate = (date: Date) => `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;

export interface AgendaTerm {
  id: string;
  label: string;
  calendar?: TimetableCalendar | null;
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

const defaultPeriods = [1, 3, 5, 7, 9].map((start) => ({ start, end: start + 1 }));

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

function MonthCalendar({ selected, bounds, offset, onMonth, onDay }: {
  selected: Date; bounds: { first: Date; last: Date } | null; offset: number;
  onMonth: (offset: number) => void; onDay: (date: Date) => void;
}) {
  const month = new Date(Date.UTC(selected.getUTCFullYear(), selected.getUTCMonth() + offset, 1));
  const end = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 0));
  return <section className="mini-month" aria-label="按日期查看授课">
    <div className="month-label"><h2>{monthText(month)}</h2><div className="month-pager">
      <button type="button" aria-label="上月" disabled={bounds != null && month <= bounds.first} onClick={() => onMonth(offset - 1)}><TeacherIcon name="left" /></button>
      <button type="button" aria-label="下月" disabled={bounds != null && end >= bounds.last} onClick={() => onMonth(offset + 1)}><TeacherIcon name="right" /></button>
    </div></div>
    <div className="month-grid">{weekdays.map((label) => <span key={label} className="weekday">{label}</span>)}
      {Array.from({ length: end.getUTCDate() }, (_, index) => {
        const date = advance(month, index);
        return <button key={index} type="button" aria-label={iso(date)} aria-pressed={iso(date) === iso(selected)}
          style={index === 0 ? { gridColumn: (month.getUTCDay() + 6) % 7 + 1 } : undefined}
          disabled={bounds != null && (date < bounds.first || date > bounds.last)} onClick={() => onDay(date)}>{index + 1}</button>;
      })}
    </div>
  </section>;
}

function useAgendaDate(term: AgendaTerm, today: string) {
  const [dates, setDates] = useState<Record<string, string>>({});
  const bounds = term.calendar ? { first: dateOf(term.calendar.starts_on), last: dateOf(term.calendar.ends_on) } : null;
  const clamp = (date: Date) => bounds ? new Date(Math.min(Math.max(+date, +bounds.first), +bounds.last)) : date;
  const currentDate = dateOf(today);
  const selected = clamp(dateOf(dates[term.id] ?? today));
  const firstDay = mondayOf(selected);
  const week = bounds ? Math.round((+firstDay - +mondayOf(bounds.first)) / (7 * dayMs)) + 1 : undefined;
  const selectDate = (value: Date) => setDates((previous) => ({ ...previous, [term.id]: iso(clamp(value)) }));
  return {
    bounds, selected, firstDay, week, selectDate,
    previous: bounds == null || firstDay > mondayOf(bounds.first) ? advance(selected, -7) : undefined,
    next: bounds == null || firstDay < mondayOf(bounds.last) ? advance(selected, 7) : undefined,
    current: bounds == null || (currentDate >= bounds.first && currentDate <= bounds.last) ? currentDate : undefined,
  };
}

function WeekButtons({ date, onDate }: { date: ReturnType<typeof useAgendaDate>; onDate: (value: Date) => void }) {
  const { firstDay, week, previous, next, current } = date;
  return <div className="week"><div className="week-step" role="group" aria-label="切换教学周">
    <button type="button" className="btn square" aria-label="上一周" disabled={!previous} onClick={() => previous && onDate(previous)}><TeacherIcon name="left" /></button>
    <span>{week == null ? `${shortDate(firstDay)} – ${shortDate(advance(firstDay, 6))}` : `第 ${week} 周`}</span>
    <button type="button" className="btn square" aria-label="下一周" disabled={!next} onClick={() => next && onDate(next)}><TeacherIcon name="right" /></button>
  </div>{current && <button type="button" className="btn jump-week" disabled={+mondayOf(current) === +firstDay} onClick={() => onDate(current)}>本周</button>}</div>;
}

function AgendaWeek({ title = "教学课表", date, slots, classes, periods, today, controls }: {
  title?: string; date: ReturnType<typeof useAgendaDate>; slots: AgendaSlot[]; classes: AgendaClass[];
  periods: AgendaPeriod[]; today: string; controls: ReactNode;
}) {
  const { firstDay, selected, week, bounds } = date;
  const rows = [...new Map<string, AgendaPeriod>([...slots, ...periods]
    .map((period) => [periodText(period.start, period.end), period])).values()].sort((a, b) => a.start - b.start || a.end - b.end);
  const days = weekdays.slice(0, Math.max(5, ...slots.map((slot) => slot.weekday + 1))).map((name, index) => {
    const day = advance(firstDay, index);
    return { label: `周${name}`, date: day, today: iso(day) === today, selected: +day === +selected };
  });
  const sessions = slots.filter((slot) => {
    const day = days[slot.weekday]?.date;
    return day && (!bounds || (day >= bounds.first && day <= bounds.last)) && inWeek(slot, week);
  });
  const range = `${shortDate(firstDay)} – ${shortDate(advance(firstDay, 6))}`;
  const tone = (course: AgendaClass) => ["blue", "teal", "slate"][classes.findIndex(({ id }) => id === course.id) % 3] ?? "blue";
  return <section className="panel agenda-panel schedule">
    <div className="panel-head"><div><h2>{title}</h2><p className="small">{range} · {week == null ? `常规排课 · ${sessions.length} 个时段` : `共 ${sessions.length} 次课`}</p></div>{controls}</div>
    <TeacherScrollFrame label="周课表">
      <div className={`timetable${days.length > 5 ? " extended-week" : ""}`} style={{ "--week-days": days.length } as React.CSSProperties}>
        <div className="tt-cell tt-label day first-period">节次</div>
        {days.map((day) => <div key={day.label} className={`tt-cell tt-label day${day.selected ? " selected" : ""}`} aria-current={day.today ? "date" : undefined}>
          <strong>{day.label}</strong><span className="date">{shortDate(day.date)}</span>
        </div>)}
        {rows.map((period) => <Fragment key={periodText(period.start, period.end)}>
          <div className="tt-cell tt-label first-period">{periodText(period.start, period.end)} 节{period.time && <span className="date">{period.time}</span>}</div>
          {days.map((day, index) => <div key={day.label} className={`tt-cell${day.selected ? " selected-column" : ""}`}>
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
      </div></TeacherScrollFrame>
    {sessions.length ? <div className="legend small">{classes.filter((course) => sessions.some((slot) => slot.course.id === course.id))
      .map((course) => <span key={course.id}><i className="swatch" data-tone={tone(course)} />{course.title}</span>)}</div>
      : <p className="empty">{slots.length ? "所选教学周没有排课。" : "本学期还没有排课。"}</p>}
  </section>;
}

export function ClassAgendaWeek(props: { term: AgendaTerm; slots: AgendaSlot[]; classes: AgendaClass[]; today: string }) {
  const date = useAgendaDate(props.term, props.today);
  return <AgendaWeek {...props} title="班级课表" date={date} periods={defaultPeriods}
    controls={<WeekButtons date={date} onDate={date.selectDate} />} />;
}

export function TeachingAgenda({ term, terms, classes, slots, todos, today, periods = defaultPeriods, onTerm, onImport, onEnvironments,
  classActions, scheduleState, classesState, todosState }: {
  term: AgendaTerm; terms: AgendaTerm[]; classes: AgendaClass[]; slots: AgendaSlot[]; todos: AgendaTodo[]; today: string;
  periods?: AgendaPeriod[]; onTerm: (id: string) => void; onImport: () => void; onEnvironments: () => void;
  classActions?: ReactNode; scheduleState?: ReactNode; classesState?: ReactNode; todosState?: ReactNode;
}) {
  const date = useAgendaDate(term, today);
  const { selected, firstDay, bounds, week } = date;
  const weekday = weekdayOf(selected);
  const [view, setView] = useState<"day" | "week">("week");
  const [mobileCalendarOpen, setMobileCalendarOpen] = useState(false);
  const [month, setMonth] = useState({ termId: term.id, offset: 0 });
  const offset = month.termId === term.id ? month.offset : 0;
  const setOffset = (value: number) => setMonth({ termId: term.id, offset: value });
  function chooseDay(value: Date) {
    date.selectDate(value);
    setOffset(0);
  }

  const calendar = <MonthCalendar selected={selected} bounds={bounds} offset={offset} onMonth={setOffset} onDay={chooseDay} />;
  const picker = <div className="mobile-days" role="group" aria-label="选择授课日期">
    {weekdays.map((name, index) => {
      const day = advance(firstDay, index);
      return <button key={index} type="button" aria-label={iso(day)} aria-pressed={weekday === index}
        disabled={bounds != null && (day < bounds.first || day > bounds.last)} onClick={() => chooseDay(day)}>
        <span>周{name}</span><strong>{day.getUTCDate()}</strong>
      </button>;
    })}
  </div>;
  const weekControls = <WeekButtons date={date} onDate={chooseDay} />;
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
      {calendar}
      <section className="term-classes"><div className="aside-heading"><h2>我的教学班</h2><span className="small">{classes.length} 个班</span></div>
        {classesState}{classes.length ? <ul className="class-index">{classes.map((course) => <li key={course.id}>
          <Link to={`/courses/${course.id}`}><span><strong>{course.title}</strong>
            <small className="small">{course.students ?? "—"} 名学生 · {course.experiments ?? "—"} 个实验</small></span><TeacherIcon name="right" /></Link>
        </li>)}</ul> : !classesState && <p className="empty">本学期暂无教学班。</p>}
        {classActions}
      </section>
    </aside><div className="folio">
      <div className="folio-top">
        <time className="folio-date" dateTime={iso(selected)}><strong className="day-number">{selected.getUTCDate()}</strong>
          <span className="date-detail"><strong>星期{weekdays[weekday]}</strong><span>{monthText(selected)}</span></span></time>
        <div role="group" aria-label="课表视图" className="view-switch">
          <button type="button" aria-pressed={view === "day"} onClick={() => setView("day")}>日程</button>
          <button type="button" aria-pressed={view === "week"} onClick={() => setView("week")}>周课表</button>
        </div>
      </div>
      <details className="mobile-calendar" onToggle={(event) => setMobileCalendarOpen(event.currentTarget.open)}>
        <summary>月历</summary>{mobileCalendarOpen && calendar}
      </details>
      {picker}
      {scheduleState}
      {view === "day" ? <section><div className="journal-heading"><h2>{week == null ? "当日常规排课" : "当日课程"}</h2>{weekControls}</div>
        {lessons.length ? <ol className="day-lessons">{lessons.map((slot) => {
          const periodsText = `第 ${periodText(slot.start, slot.end)} 节`;
          const clock = periods.find((period) => period.start === slot.start && period.end === slot.end)?.time;
          return <li key={slot.id}><Link className="lesson" to={`/courses/${slot.course.id}`}>
            <span className="lesson-clock"><strong>{clock ?? periodsText}</strong>{clock && <small>{periodsText}</small>}</span>
            <span className="lesson-details"><strong>{slot.course.lessonTitle ?? slot.course.title}</strong>
              <span>{[slot.course.group, slot.classroom, week == null && conditions(slot)].filter(Boolean).join(" · ")}</span></span><TeacherIcon name="right" />
          </Link></li>;
        })}</ol> : !scheduleState && <p className="empty">这一天没有排课。</p>}
      </section> : <AgendaWeek date={date} slots={slots} classes={classes} periods={periods} today={today} controls={weekControls} />}
      <section className="pending"><div className="journal-heading"><h2>教学待办</h2></div>{todosState}
        {todos.length ? <ul className="work-list">{todos.map((item) => <li key={item.key}><Link className="work-row" to={item.href}>
          <span><strong>{item.label}</strong><span className="small">{item.meta}</span></span><span className="count">{item.count}</span>
        </Link></li>)}</ul> : !todosState && <p className="empty">本学期暂无待处理事项。</p>}
      </section>
    </div></div>
  </>;
}
