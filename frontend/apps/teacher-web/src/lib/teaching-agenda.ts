import { useQueries, useQuery } from "@tanstack/react-query";
import { assessmentPartsApi, labAssessmentApi, teachingApi, type Publication, type TimetableSchedule } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import type { AgendaClass, AgendaSlot } from "@/components/teaching-agenda";
import { allPages } from "./all-pages";

export const schoolToday = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(new Date());

export const coursePublications = (courseId: string) => allPages((page) => teachingApi.publications(courseId, { page }));
export const publicationQuery = (courseId: string) => ({
  queryKey: keys.publications(courseId, { scope: "agenda" }),
  queryFn: () => coursePublications(courseId),
});
export const reportsQuery = (courseId: string, publicationId: string) => ({
  queryKey: ["assessment-report-queue", courseId, publicationId],
  queryFn: () => assessmentPartsApi.reports(courseId, publicationId),
});
export const releaseQuery = (courseId: string, publicationId: string) => ({
  queryKey: ["lab-grade-release", courseId, publicationId],
  queryFn: () => labAssessmentApi.releaseStatus(courseId, publicationId),
});
export const reviewLink = (courseId: string, publicationId: string) => `/courses/${courseId}/publishing/${publicationId}/reviews?tab=reports`;

export function useAgendaPublications(courseId: string) {
  return useQuery(publicationQuery(courseId));
}

export function usePublicationReports(courseId: string, publications: Publication[]) {
  return useQueries({ queries: publications.map((publication) => ({
    ...reportsQuery(courseId, publication.public_id),
    enabled: isReportPublication(publication),
  })) });
}

export function isReportPublication(publication: Publication) {
  return ["PUBLISHED", "CLOSED"].includes(publication.status) && publication.report_required !== false;
}

export function asAgendaSlots(schedules: TimetableSchedule[], classes: AgendaClass[]): AgendaSlot[] {
  const byId = new Map(classes.map((course) => [course.id, course]));
  return schedules.flatMap((slot, index) => {
    const course = slot.course_id ? byId.get(slot.course_id) : undefined;
    if (!course || slot.weekday < 1 || slot.weekday > 7) return [];
    return [{ id: `${course.id}-${index}`, course, weekday: slot.weekday - 1, start: slot.start_period, end: slot.end_period,
      classroom: slot.classroom, weekStart: slot.week_start, weekEnd: slot.week_end, parity: slot.week_parity }];
  });
}

export function schoolDateTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "short",
  }).format(date);
}
