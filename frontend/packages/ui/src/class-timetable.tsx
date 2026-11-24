import type { TimetableData, TimetableSchedule } from "@edu/api-client";
import { Fragment, type ReactNode } from "react";
import { Panel } from "./primitives";
import { RequestStateView } from "./states";

const weekdays = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export function ScheduleSlots({ slots }: { slots: TimetableSchedule[] }) {
  return <div>{slots.length === 0 ? <small>暂无排课</small> : slots.map((slot, index) => <Fragment key={index}><small>
    {weekdays[slot.weekday]} 第 {slot.start_period}—{slot.end_period} 节
    {slot.week_start != null && ` · 第 ${slot.week_start}—${slot.week_end} 周`}
    {slot.week_parity === "ODD" ? "（单周）" : slot.week_parity === "EVEN" ? "（双周）" : ""}
    {` · ${slot.classroom || "教室待定"}`}
  </small><br /></Fragment>)}</div>;
}

export function ClassTimetable({ data, loading, error, retry, onTermChange, classLink, title = "我的课表" }: {
  title?: string;
  data?: TimetableData;
  loading: boolean;
  error: Error | null;
  retry: () => void;
  onTermChange: (term: string) => void;
  classLink: (id: string, title: string) => ReactNode;
}) {
  return <Panel className="section" title={<h2>{title}</h2>} actions={data && <label>学期{" "}
    <select className="field" value={data.term.public_id} onChange={(event) => onTermChange(event.target.value)}>
      {data.terms.map((term) => <option key={term.public_id} value={term.public_id}>{term.name}</option>)}
    </select>
  </label>}>
    <RequestStateView loading={loading} error={error} onRetry={retry} empty={!data?.classes.length}
      emptyState={<p className="subtle">本学期暂无教学班。</p>}>
      {data?.classes.map((course) => {
        const slots = data.schedules.filter((slot) => slot.course_id === course.course_id);
        return <div className="item" key={course.course_id}>
          <div>{classLink(course.course_id, course.course_title)}
            <small>{course.course_code} · {course.instructor_name}</small></div>
          <ScheduleSlots slots={slots} />
        </div>;
      })}
    </RequestStateView>
  </Panel>;
}
