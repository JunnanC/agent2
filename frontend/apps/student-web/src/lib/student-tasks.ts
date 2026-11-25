import { taskApi } from "@edu/api-client";

export async function listStudentTasks(filters: { course_id?: string; status?: string } = {}) {
  const query = { ...filters, page_size: 100 };
  const first = await taskApi.list(query);
  const rows = [...first.rows];
  for (let page = 2; (page - 1) * first.pageSize < first.total; page += 1) {
    const next = await taskApi.list({ ...query, page });
    if (!next.rows.length) break;
    rows.push(...next.rows);
  }
  return { ...first, rows };
}
