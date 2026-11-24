import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { TimetableSchedule } from "@edu/api-client";
import { Icon, RequestStateView, type CalendarItem } from "@edu/ui";
import type { useStudentTimetable } from "@/lib/use-student-timetable";

const weekdays = ["一", "二", "三", "四", "五", "六", "日"];
const dateKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

function shiftDate(date: Date, days: number) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days, 12);
}

function MonthCalendar({ date, items, onSelect }: { date: Date; items: CalendarItem[]; onSelect: (key: string) => void }) {
  const [offset, setOffset] = useState(0);
  const first = new Date(date.getFullYear(), date.getMonth() + offset, 1, 12);
  const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const counts = new Map<string, number>();
  items.forEach(item => counts.set(item.date, (counts.get(item.date) ?? 0) + 1));
  return <section className="agenda-month" aria-label="任务日历">
    <div className="agenda-section-title">
      <h2>{first.getFullYear()} 年 {first.getMonth() + 1} 月</h2>
      <div className="agenda-pager">
        <button type="button" aria-label="上个月" onClick={() => setOffset(offset - 1)}><Icon name="chevron-left" size={15} /></button>
        <button type="button" aria-label="下个月" onClick={() => setOffset(offset + 1)}><Icon name="chevron-right" size={15} /></button>
      </div>
    </div>
    <div className="agenda-month-grid">
      {weekdays.map(day => <small key={day}>{day}</small>)}
      {Array.from({ length: (first.getDay() + 6) % 7 }, (_, i) => <span key={`blank-${i}`} />)}
      {Array.from({ length: days }, (_, i) => {
        const day = shiftDate(first, i);
        const key = dateKey(day);
        const count = counts.get(key) ?? 0;
        return <button key={key} type="button" aria-pressed={key === dateKey(date)}
          aria-label={`${day.getMonth() + 1} 月 ${day.getDate()} 日，${count ? `${count} 项待办任务` : "无待办任务"}`}
          data-has-tasks={count > 0} onClick={() => { setOffset(0); onSelect(key); }}>{day.getDate()}</button>;
      })}
    </div>
  </section>;
}

function slotKey(slot: TimetableSchedule) {
  return [slot.course_id, slot.course_code, slot.weekday, slot.start_period, slot.end_period,
    slot.week_start, slot.week_end, slot.week_parity, slot.classroom].join("|");
}

function Lesson({ slot, week }: { slot: TimetableSchedule; week: boolean }) {
  const weeks = slot.week_start != null && slot.week_end != null ? `第 ${slot.week_start}–${slot.week_end} 周` : "";
  const parity = slot.week_parity === "ODD" ? "单周" : slot.week_parity === "EVEN" ? "双周" : "";
  const content = <>
    <span className="agenda-period"><strong>{slot.start_period}{slot.start_period !== slot.end_period && `–${slot.end_period}`}</strong>
      <small>{week ? `周${weekdays[slot.weekday - 1]} · 节次` : "节次"}</small></span>
    <span className="agenda-lesson-copy"><strong>{slot.course_title}</strong>
      <small>{[slot.course_code, slot.classroom || "教室待定", weeks, parity].filter(Boolean).join(" · ")}</small></span>
    {slot.course_id && <Icon name="chevron-right" size={16} />}
  </>;
  return slot.course_id ? <Link className="agenda-lesson" to={`/courses/${slot.course_id}`}>{content}</Link>
    : <div className="agenda-lesson">{content}</div>;
}

interface JournalProps {
  schedule: ReturnType<typeof useStudentTimetable>;
  date: string;
  onSelect: (date: string) => void;
  items: CalendarItem[];
  children: ReactNode;
}

export function StudentJournal({ schedule, date, onSelect, items, children }: JournalProps) {
  const [weekView, setWeekView] = useState(false);
  const { timetable, selectTerm } = schedule;
  const selected = new Date(`${date}T12:00:00`);
  const weekday = (selected.getDay() + 6) % 7;
  const monday = shiftDate(selected, -weekday);
  const data = timetable.data;
  const slots = (data?.schedules ?? []).filter(slot => weekView || slot.weekday === weekday + 1)
    .sort((a, b) => a.weekday - b.weekday || a.start_period - b.start_period);
  const requestState = { loading: timetable.isPending, error: timetable.error, onRetry: () => void timetable.refetch() };

  return <>
    <header className="agenda-heading">
      <h1>学习日程</h1>
      <div>{data && <select aria-label="课表学期" value={data.term.public_id} onChange={event => selectTerm(event.target.value)}>
        {data.terms.map(term => <option key={term.public_id} value={term.public_id}>{term.name}</option>)}
      </select>}
        <Link className="btn primary" to="/courses/join"><Icon name="plus" size={16} />加入教学班</Link>
      </div>
    </header>
    <div className="student-journal">
      <aside className="agenda-aside">
        <MonthCalendar key={date.slice(0, 7)} date={selected} items={items} onSelect={onSelect} />
        <section className="agenda-classes">
          <div className="agenda-section-title"><h2>我的教学班</h2><Link to="/courses">管理课程</Link></div>
          <RequestStateView {...requestState} empty={!data?.classes.length} emptyState={<p className="agenda-empty">本学期暂无教学班。</p>}>
            {data?.classes.map(course => <Link className="agenda-index-row" to={`/courses/${course.course_id}`} key={course.course_id}>
              <span><strong>{course.course_title}</strong><small>{[course.course_code, course.instructor_name].filter(Boolean).join(" · ")}</small></span>
              <Icon name="chevron-right" size={15} />
            </Link>)}
          </RequestStateView>
        </section>
      </aside>
      <div className="agenda-folio">
        <div className="agenda-folio-head">
          <time dateTime={date}><strong>{selected.getDate()}</strong>
            <span><b>星期{weekdays[weekday]}</b><small>{selected.getFullYear()} 年 {selected.getMonth() + 1} 月</small></span></time>
          <div role="group" aria-label="课表视图" className="agenda-switch">
            <button type="button" aria-pressed={!weekView} onClick={() => setWeekView(false)}>日程</button>
            <button type="button" aria-pressed={weekView} onClick={() => setWeekView(true)}>周课表</button>
          </div>
        </div>
        <div className="agenda-week-days" role="group" aria-label="选择学习日期">
          {weekdays.map((day, index) => {
            const target = shiftDate(monday, index);
            return <button key={day} type="button" aria-label={dateKey(target)} aria-pressed={weekday === index}
              onClick={() => onSelect(dateKey(target))}><small>周{day}</small><b>{target.getDate()}</b></button>;
          })}
        </div>
        <div className="agenda-section-title agenda-lesson-title">
          <h2>{weekView ? "学期周课表" : `周${weekdays[weekday]}排课规则`}</h2>
          <div className="agenda-week-step">
            <button type="button" aria-label="上一周" onClick={() => onSelect(dateKey(shiftDate(selected, -7)))}><Icon name="chevron-left" size={14} /></button>
            <span>{monday.getMonth() + 1}/{monday.getDate()} – {shiftDate(monday, 6).getMonth() + 1}/{shiftDate(monday, 6).getDate()}</span>
            <button type="button" aria-label="下一周" onClick={() => onSelect(dateKey(shiftDate(selected, 7)))}><Icon name="chevron-right" size={14} /></button>
          </div>
        </div>
        <RequestStateView {...requestState} empty={!slots.length} emptyState={<p className="agenda-empty">{weekView ? "本学期暂无排课。" : "所选星期暂无排课规则。"}</p>}>
          <ul className="agenda-lessons">{slots.map(slot => <li key={slotKey(slot)}><Lesson slot={slot} week={weekView} /></li>)}</ul>
        </RequestStateView>
        <section className="agenda-tasks">
          <div className="agenda-section-title"><h2>待完成任务</h2><Link to="/experiments">全部实验</Link></div>
          {children}
        </section>
      </div>
    </div>
  </>;
}
