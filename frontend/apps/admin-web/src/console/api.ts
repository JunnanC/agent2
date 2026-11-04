import { request } from "@edu/auth-client";

export interface Account {
  public_id: string;
  display_name: string;
  username: string;
  email: string;
  account_status: string;
  row_version: number;
}
export interface Role {
  public_id: string;
  user_id: string;
  display_name: string;
  status: string;
}
export interface Course {
  public_id: string;
  title: string;
  code: string;
  owner_id: string;
  owner_name: string;
  status: string;
  summary: string;
  description: string;
  active_enrollment_count: number;
  teaching_start: string | null;
  teaching_end: string | null;
  row_version: number;
}
export interface Image {
  public_id: string;
  registry: string;
  repository: string;
  display_tag: string;
  digest: string;
  scan_status: string;
  approval_status: string;
  row_version: number;
}
export interface Runtime {
  public_id: string;
  name: string;
  code: string;
  driver: string;
  status: string;
  health_status: string;
  capacity_cpu_millicores: number;
  available_cpu_millicores: number;
  capacity_memory_mb: number;
  available_memory_mb: number;
  last_health_at?: string;
}
export interface Instance {
  public_id: string;
  course_id: string;
  student_id: string;
  status: string;
  runtime_driver: string;
  runtime_health: string;
  external_status: string;
}
export interface Audit {
  id: string;
  occurred_at: string;
  actor: string;
  action: string;
  target: string;
  result: string;
  trace_id: string;
}
export interface Overview {
  runtime?: { status?: string };
  logs?: { status?: string };
  alerts?: { code: string; message: string; severity: string }[];
  instances?: Record<string, number>;
}

// Fetch every server page before applying local role filters; never label a partial page as a platform total.
export async function listAll<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T[]> {
  const rows: T[] = [];
  for (let page = 1; ; page++) {
    const response = await request<T[]>(path, {
      query: { page, page_size: 100 },
      signal,
    });
    rows.push(...response.data);
    const total = response.meta.total;
    if (
      typeof total === "number"
        ? rows.length >= total
        : response.data.length < 100
    )
      return rows;
    if (!response.data.length || page >= 1000)
      throw new Error("列表加载不完整，请缩小查询范围后重试");
  }
}

export function splitAccounts(
  users: Account[],
  teachers: Role[],
  admins: Role[],
) {
  const teacherIds = new Set(teachers.map((role) => role.user_id));
  const adminIds = new Set(admins.map((role) => role.user_id));
  return {
    teachers: users.filter((user) => teacherIds.has(user.public_id)),
    students: users.filter(
      (user) =>
        !teacherIds.has(user.public_id) && !adminIds.has(user.public_id),
    ),
  };
}

export function usage(total?: number, available?: number) {
  if (total == null || available == null || total <= 0) return null;
  return Math.max(
    0,
    Math.min(100, Math.round(((total - available) / total) * 100)),
  );
}

export function imageAddress(value: string) {
  const address = value
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/$/, "");
  const slash = address.indexOf("/");
  if (slash <= 0 || slash === address.length - 1 || /\s|@|[?#]/.test(address))
    throw new Error(
      "请输入包含仓库和路径的镜像地址，不含标签、digest 或查询参数",
    );
  const registry = address.slice(0, slash),
    repository = address.slice(slash + 1);
  if (repository.includes(":")) throw new Error("版本请填写在版本字段中");
  return { registry, repository };
}
