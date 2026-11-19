import { StudentImport } from "./StudentImport";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { request, ApiError } from "@edu/auth-client";
import { AppShell } from "@edu/ui";
import { useSession } from "../app/session";
import { useRecentAuthGuard } from "../lib/recent-auth";
import {
  listAll,
  splitAccounts,
  usage,
  imageAddress,
  type Account,
  type Role,
  type Course,
  type Image,
  type Runtime,
  type ResourceProfile,
  type Audit,
  type Overview,
} from "./api";
import { Status, Table, List, Modal, Fields, ErrorState, Meter } from "./ui";
import { date } from "./format";
import "./console.css";

const names = {
  overview: "运行概览",
  courses: "课程与班级",
  students: "学生管理",
  teachers: "教师管理",
  images: "镜像管理",
  profiles: "资源规格",
  resources: "服务与资源",
  logs: "操作日志",
};
const navLabels = {
  overview: "概览",
  courses: "课程",
  students: "学生",
  teachers: "教师",
  images: "镜像",
  profiles: "规格",
  resources: "资源",
  logs: "日志",
};
type Page = keyof typeof names;
const navIcons = {
  overview: "layers",
  courses: "book",
  students: "users",
  teachers: "user",
  images: "box",
  profiles: "cpu",
  resources: "server",
  logs: "list",
} as const;
const descriptions: Record<Page, string> = {
  overview: "",
  courses: "",
  students: "",
  teachers: "",
  images: "",
  profiles: "",
  resources: "",
  logs: "",
};
const qk = (path: string) => ["admin-console", path];
function useList<T>(path: string) {
  return useQuery({
    queryKey: qk(path),
    queryFn: ({ signal }) => listAll<T>(path, signal),
  });
}
const accountsPath = "/platform/users",
  rolesPath = "/platform/teacher-qualifications",
  adminsPath = "/platform/admin-assignments",
  coursesPath = "/platform/courses",
  imagesPath = "/platform/images",
  profilesPath = "/platform/resource-profiles",
  runtimesPath = "/platform/runtime-adapters",
  logsPath = "/platform/operations/audit";
const accountStates: [string, string][] = [
  ["ACTIVE", "正常"],
  ["DISABLED", "已禁用"],
];
function formatCores(millicores: number): string {
  return String(Number((millicores / 1000).toFixed(2)));
}
function formatMemory(megabytes: number): string {
  return megabytes >= 1024 && megabytes % 1024 === 0
    ? `${megabytes / 1024} GB`
    : `${megabytes} MB`;
}
type Dialog =
  | { kind: "account"; account: Account }
  | { kind: "person"; account: Account; teacher: boolean }
  | { kind: "course"; course: Course }
  | { kind: "image"; image: Image }
  | { kind: "image-form" }
  | { kind: "image-rename"; image: Image }
  | { kind: "image-toggle"; image: Image }
  | { kind: "profile"; profile: ResourceProfile }
  | { kind: "profile-form" }
  | { kind: "profile-toggle"; profile: ResourceProfile }
  | { kind: "audit"; audit: Audit }
  | { kind: "runtime"; runtime: Runtime };

export default function Console() {
  const location = useLocation(),
    navigate = useNavigate(),
    session = useSession(),
    client = useQueryClient();
  const path = location.pathname.slice(1),
    hash = location.hash.slice(1);
  const aliases: Record<string, Page> = {
    users: "students",
    audit: "logs",
    governance: "overview",
    incidents: "resources",
    agents: "overview",
  };
  const candidate = path || hash || "overview";
  const current: Page = Object.hasOwn(names, candidate)
    ? (candidate as Page)
    : (aliases[candidate] ?? "overview");
  useEffect(() => {
    document.title = "实验教学平台";
  }, []);
  function go(page: Page, tab?: string, query?: Record<string, string>) {
    const params = new URLSearchParams();
    if (tab) params.set("tab", tab);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value) params.set(key, value);
    }
    const search = params.toString();
    navigate(page === "overview" ? "/" : `/${page}${search ? `?${search}` : ""}`);
  }
  const adminNav = (Object.keys(names) as Page[]).map((page) => ({
    label: navLabels[page],
    path: page,
    icon: navIcons[page],
  }));
  return (
    <AppShell
      brand="实验教学平台"
      domainLabel="管理控制台"
      nav={adminNav}
      activePath={current}
      onNavigate={(path) => go(path as Page)}
      avatar={{
        name: session.me?.display_name || "运维管理员",
        role: "运维管理员",
        badge: session.me?.display_name?.slice(0, 1) || "运",
      }}
      avatarItems={[
        {
          label: "退出",
          onClick: () =>
            void session.logout().then(() => {
              client.clear();
              navigate("/login");
            }),
        },
      ]}
      navigationPosition="side"
      collapsible
      collapseStorageKey="admin-console-nav-collapsed"
    >
      <div className="admin-console">
        <a className="console-skip" href="#console-main">跳到主要内容</a>
        <main id="console-main" tabIndex={-1}>
          <PageContent key={current} current={current} go={go} />
        </main>
      </div>
    </AppShell>
  );
}

const AUDIT_ACTION_LABEL: Record<string, string> = {
  "auth.login": "登录",
  "auth.logout": "退出登录",
  "auth.session.denied": "会话过期",
  "assessment.choice.submit": "选择题交卷",
  "assessment.programming.submit": "编程与报告交卷",
  "assessment.report.grade": "报告评分",
  "enrollment.review": "选课审核",
  "enrollment.apply": "选课申请",
  "enrollment.withdraw": "撤回选课申请",
  "course.create": "创建课程",
  "course.published": "发布课程",
  "course.publish": "发布课程",
  "course.chapter.create": "创建章节",
  "course.chapter.status": "调整章节状态",
  "course.material_version.status": "调整材料状态",
  "labtemplate.create": "创建实验模板",
  "labtemplate.version.create": "创建模板版本",
  "labtemplate.version.publish": "发布模板版本",
  "labtemplate.precheck.request": "提交模板预检",
  "experiment.publication.create": "创建实验发布",
  "experiment.publication.publish": "发布实验",
  "governance.image.create": "登记镜像",
  "governance.quota.reserve": "预留配额",
  "governance.quota.release": "释放配额",
};

const AUDIT_SUCCEEDED = "SUCCEEDED";

function isFailedAudit(entry: Audit): boolean {
  return Boolean(entry.result) && entry.result !== AUDIT_SUCCEEDED;
}

function describeAudit(entry: Audit): string {
  return AUDIT_ACTION_LABEL[entry.action] ?? entry.action;
}

function describeTarget(target: string | undefined): string {
  if (!target) return "";
  const [kind, id] = target.split(":");
  if (!id) return target;
  return `${kind} ${id.slice(0, 8)}…`;
}

function PageContent({
  current,
  go,
}: {
  current: Page;
  go: (page: Page, tab?: string, query?: Record<string, string>) => void;
}) {
  const client = useQueryClient(),
    recentAuth = useRecentAuthGuard();
  const [dialog, setDialog] = useState<Dialog | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [toast, setToast] = useState("");
  const [params, setParams] = useSearchParams();
  const resourceTab = params.get("tab") === "health" ? "health" : "usage";
  const classId = params.get("class") ?? "";
  const classType = params.get("type") === "teaching" ? "teaching" : "administrative";
  const memberPath = classType === "teaching" ? `/platform/courses/${classId}/members` : `/platform/administrative-classes/${classId}/members`;
  const classes = useQuery({ queryKey: qk("/platform/administrative-classes"), queryFn: ({ signal }) => request<Array<{ public_id: string; name: string; code: string; status: string }>>("/platform/administrative-classes", { signal }).then((r) => r.data), enabled: current === "students" });
  const members = useQuery({ queryKey: qk(memberPath), queryFn: ({ signal }) => request<{ class: { name: string }; members: Array<{ public_id: string; student_id: string; student_name: string }> }>(memberPath, { signal }).then((r) => r.data), enabled: current === "students" && Boolean(classId) });
  const [courseTab, setCourseTab] = useState("info"),
    [from, setFrom] = useState(""),
    [to, setTo] = useState("");
  const users = useList<Account>(accountsPath),
    roles = useList<Role>(rolesPath),
    admins = useList<Role>(adminsPath),
    courses = useList<Course>(coursesPath);
  const images = useList<Image>(imagesPath),
    profiles = useList<ResourceProfile>(profilesPath),
    runtimes = useList<Runtime>(runtimesPath),
    audits = useList<Audit>(logsPath);
  const overview = useQuery({
    queryKey: qk("/platform/operations/overview"),
    queryFn: ({ signal }) =>
      request<Overview>("/platform/operations/overview", { signal }).then(
        (r) => r.data,
      ),
  });
  const people = splitAccounts(
    users.data ?? [],
    roles.data ?? [],
    admins.data ?? [],
  );
  const allCourses = courses.data ?? [],
    allImages = images.data ?? [];
  const allProfiles = useMemo(
    () => [...(profiles.data ?? [])].sort((left, right) => left.cpu_millicores - right.cpu_millicores),
    [profiles.data],
  );
  const allRuntimes = useMemo(() => runtimes.data ?? [], [runtimes.data]);
  const allAudits = useMemo(() => audits.data ?? [], [audits.data]);
  const issues = useMemo(() => {
    const items: Array<{
      key: string;
      kind: string;
      label: string;
      detail?: string;
      action: () => void;
    }> = [];
    for (const alert of overview.data?.alerts ?? []) {
      items.push({
        key: `alert-${alert.code}`,
        kind: "告警",
        label: alert.message,
        detail: alert.severity,
        action: () => go("resources"),
      });
    }
    for (const runtime of allRuntimes.filter(
      (item) => item.health_status && !["HEALTHY", "OK"].includes(item.health_status),
    )) {
      items.push({
        key: `runtime-${runtime.public_id}`,
        kind: "健康",
        label: `${runtime.name} 健康异常`,
        detail: runtime.health_status,
        action: () => go("resources", "health"),
      });
    }
    for (const entry of allAudits
      .filter((item) => isFailedAudit(item) && !item.action.startsWith("auth.session."))
      .slice(0, 3)) {
      const actorName = users.data?.find((u) => u.public_id === entry.actor)?.display_name ?? entry.actor;
      items.push({
        key: `audit-${entry.id}`,
        kind: "失败操作",
        label: `${describeAudit(entry)}失败 · ${actorName}`,
        detail: `${describeTarget(entry.target)} · ${new Date(entry.occurred_at).toLocaleString("zh-CN")}`,
        action: () => go("logs", undefined, { result: "FAILED", action: entry.action }),
      });
    }
    return items;
  }, [overview.data, allRuntimes, allAudits, users.data, go]);
  const userName = (id: string) =>
    users.data?.find((u) => u.public_id === id)?.display_name ?? id;
  const open = (value: Dialog) => {
    setDialog(value);
    setError("");
    setToast("");
    setCourseTab("info");
  };
  const close = () => {
    if (!busy) {
      setDialog(null);
      setError("");
    }
  };
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["admin-console"] });
  };
  async function mutate(action: () => Promise<unknown>, message: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await action();
      setDialog(null);
      setToast(message);
      refresh();
    } catch (cause) {
      if (recentAuth.intercept(cause, () => void mutate(action, message))) {
        setDialog(null);
      } else {
        setError(
          cause instanceof ApiError && cause.status === 412
            ? "数据已被其他操作更新，请关闭弹窗并刷新列表后重试"
            : cause instanceof Error
              ? cause.message
              : "操作失败，请重试",
        );
      }
    } finally {
      setBusy(false);
    }
  }
  const action = (label: string, handler: () => void, danger = false) => (
    <button className={`link ${danger ? "danger" : ""}`} onClick={handler}>
      {label}
    </button>
  );
  const required =
    current === "students" || current === "teachers" || current === "overview"
      ? [users, roles, admins, courses]
      : current === "courses"
        ? [courses]
        : current === "images"
          ? [images]
          : current === "profiles"
            ? [profiles]
            : current === "logs"
              ? [audits]
              : [runtimes, overview];
  const failure = required.find((q) => q.error);
  let content: ReactNode;
  if (failure) content = <ErrorState error={failure.error} retry={refresh} />;
  else if (required.some((q) => q.isPending))
    content = (
      <div className="empty" role="status">
        正在加载{names[current]}
      </div>
    );
  else if (current === "students") {
    content = <>
      {!classId && <StudentImport onComplete={() => { void refresh(); }} />}
      {classId ? <div className="class-detail">
        <button className="class-back" onClick={() => setParams({})}>返回班级列表</button>
        <div className="class-detail-head">
          <div className="class-title-line">
            <h2>{members.data?.class.name ?? "班级学生名单"}</h2>
            <span className="class-type-badge">{classType === "teaching" ? "教学班" : "行政班"}</span>
            <span className="class-student-count">共 {members.data?.members.length ?? 0} 名学生</span>
          </div>
        </div>
        {members.isPending ? <div className="console-list class-roster-list"><p className="empty" role="status">正在加载名单</p></div> : members.error ? <div className="console-list class-roster-list"><ErrorState error={members.error} retry={() => void members.refetch()} /></div> : <div className="console-list class-roster-list">
          <Table headings={["学生", "账号状态", "操作"]} className="class-roster-table" empty={!members.data?.members.length} emptyText="该班级暂无学生名单">
            {(members.data?.members ?? []).map((member) => { const user = users.data?.find((item) => item.public_id === member.student_id); return <tr key={member.public_id}><td data-label="成员"><strong>{member.student_name}</strong><span className="mono muted">{member.student_id}</span></td><td data-label="账号状态"><Status value={user?.account_status} /></td><td data-label="操作">{user && action("详情", () => open({ kind: "person", account: user, teacher: false }))}</td></tr>; })}
          </Table>
        </div>}
      </div> : classes.isPending ? <p role="status">正在加载班级</p> : classes.error ? <ErrorState error={classes.error} retry={() => void classes.refetch()} /> : <List rows={[...allCourses.filter((course) => ["PUBLISHED", "CLOSED"].includes(course.status)).map((course) => ({ public_id: course.public_id, name: course.title, code: course.code, type: "teaching" })), ...(classes.data ?? []).filter((item) => item.status === "ACTIVE").map((item) => ({ ...item, type: "administrative" }))]} text={(item) => `${item.name} ${item.code}`} placeholder="搜索班级名称或代码" headings={["班级", "代码", "类型", "操作"]} storageKey="admin-classes-list" tableClassName="classes-table" reserveRows render={(item) => <tr key={`${item.type}-${item.public_id}`}><td data-label="班级">{item.name}</td><td data-label="代码">{item.code}</td><td data-label="类型">{item.type === "teaching" ? "教学班" : "行政班"}</td><td data-label="操作">{action("查看学生名单", () => setParams({ class: item.public_id, type: item.type }))}</td></tr>} />}
    </>;
  } else if (current === "teachers") {
    const isTeacher = current === "teachers",
      data = isTeacher ? people.teachers : people.students;
    content = (
      <List
        rows={data}
        text={(u) =>
          `${u.display_name} ${u.public_id} ${u.email} ${u.username}`
        }
        states={accountStates}
        state={(u) => u.account_status}
        placeholder="搜索姓名、账号 ID 或邮箱"
        headings={[
          isTeacher ? "教师 / ID" : "学生 / ID",
          "邮箱",
          ...(isTeacher ? ["创建课程数量"] : []),
          "账号状态",
          "操作",
        ]}
        render={(u) => (
          <tr key={u.public_id}>
            <td data-label={isTeacher ? "教师 / ID" : "学生 / ID"}>
              <strong>{u.display_name}</strong>
              <span className="mono muted">{u.public_id}</span>
            </td>
            <td data-label="邮箱">{u.email}</td>
            {isTeacher && (
              <td className="num" data-label="创建课程">
                {allCourses.filter((c) => c.owner_id === u.public_id).length}
              </td>
            )}
            <td data-label="账号状态">
              <Status value={u.account_status} />
            </td>
            <td className="actions" data-label="操作">
              {action("详情", () =>
                open({ kind: "person", account: u, teacher: isTeacher }),
              )}
              {action(
                u.account_status === "ACTIVE" ? "禁用" : "恢复",
                () => open({ kind: "account", account: u }),
                u.account_status === "ACTIVE",
              )}
            </td>
          </tr>
        )}
      />
    );
  } else if (current === "courses") {
    content = (
      <>
        <List
          rows={allCourses}
          text={(c) => `${c.title} ${c.public_id} ${c.code} ${c.owner_name}`}
          states={["PUBLISHED", "DRAFT", "CLOSED", "ARCHIVED"].map(
            (s) =>
              [
                s,
                {
                  PUBLISHED: "已发布",
                  DRAFT: "草稿",
                  CLOSED: "已关闭",
                  ARCHIVED: "已归档",
                }[s]!,
              ] as [string, string],
          )}
          state={(c) => c.status}
          placeholder="搜索课程名称、ID 或教师"
          tableClassName="courses-table"
          reserveRows
          headings={[
            "课程 / ID",
            "任课教师",
            "学生人数",
            "课程状态",
            "教学时间",
            "操作",
          ]}
          render={(c) => (
            <tr key={c.public_id}>
              <td data-label="课程 / ID">
                <strong>{c.title}</strong>
                <span className="mono muted">{c.public_id}</span>
              </td>
              <td data-label="任课教师">{c.owner_name}</td>
              <td className="num" data-label="学生人数">{c.active_enrollment_count}</td>
              <td data-label="课程状态">
                <Status value={c.status} />
              </td>
              <td className="mono muted" data-label="教学时间">{date(c.teaching_start)}</td>
              <td className="actions" data-label="操作">
                {action("详情", () => open({ kind: "course", course: c }))}
                <button
                  className="link danger"
                  disabled
                  title="后端课程下架能力尚未开放"
                >
                  下架
                </button>
              </td>
            </tr>
          )}
        />
      </>
    );
  } else if (current === "images") {
    content = (
      <>
        <List
          rows={allImages}
          text={(i) =>
            `${i.repository} ${i.registry} ${i.display_tag} ${i.public_id}`
          }
          states={["APPROVED", "RETIRED", "PENDING", "REJECTED"].map(
            (s) =>
              [
                s,
                {
                  APPROVED: "已批准",
                  RETIRED: "已停用",
                  PENDING: "待处理",
                  REJECTED: "已拒绝",
                }[s]!,
              ] as [string, string],
          )}
          state={(i) => i.approval_status}
          placeholder="搜索镜像名称、地址或版本"
          headings={[
            "镜像 / ID",
            "镜像地址及版本",
            "扫描状态",
            "使用状态",
            "操作",
          ]}
          render={(i) => (
            <tr key={i.public_id}>
              <td data-label="镜像 / ID">
                <strong>{i.display_name || i.repository.split("/").at(-1)}</strong>
                <span className="mono muted">{i.public_id}</span>
              </td>
              <td data-label="地址及版本">
                <div className="mono break">
                  {i.registry}/{i.repository}
                </div>
                <span className="mono muted">{i.display_tag || "—"}</span>
              </td>
              <td data-label="扫描状态">
                <Status value={i.scan_status} />
              </td>
              <td data-label="使用状态">
                <Status value={i.approval_status} />
              </td>
              <td className="actions" data-label="操作">
                {action("详情", () => open({ kind: "image", image: i }))}
                {action("改名", () => open({ kind: "image-rename", image: i }))}
                {action(
                  i.approval_status === "APPROVED" ? "停用" : "启用",
                  () => open({ kind: "image-toggle", image: i }),
                )}
              </td>
            </tr>
          )}
        />
      </>
    );
  } else if (current === "profiles") {
    content = (
      <>
        <List
          rows={allProfiles}
          text={(p) => `${p.name} ${p.code} ${p.public_id}`}
          states={[
            ["ACTIVE", "已启用"],
            ["RETIRED", "已停用"],
          ]}
          state={(p) => p.status}
          placeholder="搜索规格名称或编码"
          headings={["规格", "CPU / 内存", "磁盘", "状态", "操作"]}
          render={(p) => (
            <tr key={p.public_id}>
              <td data-label="规格">
                <strong>{p.name}</strong>
                <span className="mono muted">{p.code}</span>
              </td>
              <td className="num" data-label="CPU / 内存">
                {formatCores(p.cpu_millicores)} 核 / {formatMemory(p.memory_mb)}
              </td>
              <td className="num" data-label="磁盘">
                {p.disk_gb} GB
              </td>
              <td data-label="状态">
                <Status value={p.status} />
              </td>
              <td className="actions" data-label="操作">
                {action("详情", () => open({ kind: "profile", profile: p }))}
                {action(
                  p.status === "ACTIVE" ? "停用" : "启用",
                  () => open({ kind: "profile-toggle", profile: p }),
                  p.status === "ACTIVE",
                )}
              </td>
            </tr>
          )}
        />
      </>
    );
  } else if (current === "logs") {
    const isIsoDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value);
    const failedOnly = params.get("result") === "FAILED";
    const data = allAudits.filter(
      (l) =>
        (!failedOnly || isFailedAudit(l)) &&
        (!isIsoDate(from) ||
          new Date(l.occurred_at).toLocaleDateString("sv-SE", {
            timeZone: "Asia/Shanghai",
          }) >= from) &&
        (!isIsoDate(to) ||
          new Date(l.occurred_at).toLocaleDateString("sv-SE", {
            timeZone: "Asia/Shanghai",
          }) <= to),
    );
    content = (
      <>
        <div className="logs-table">
          <List
          rows={data}
          text={(l) => `${l.action} ${describeAudit(l)} ${l.target} ${l.actor} ${userName(l.actor)} ${l.trace_id}`}
          states={[...new Set(allAudits.map((l) => l.action))].map((s) => [s, AUDIT_ACTION_LABEL[s] ?? s])}
          state={(l) => l.action}
          initialState={params.get("action") ?? ""}
          placeholder="搜索操作、对象、操作者或 Trace ID"
          extra={
            <>
              <label className="muted" style={{ display: "inline-flex", gap: 6, alignItems: "center", whiteSpace: "nowrap" }}>
                <input
                  type="checkbox"
                  style={{ width: 16, height: 16, minWidth: 16, margin: 0 }}
                  checked={failedOnly}
                  onChange={(e) => go("logs", undefined, e.target.checked ? { result: "FAILED" } : {})}
                />
                只看失败
              </label>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={10}
                  placeholder="YYYY-MM-DD"
                  aria-label="开始日期（YYYY-MM-DD）"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                />
                <span className="muted">至</span>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={10}
                  placeholder="YYYY-MM-DD"
                  aria-label="结束日期（YYYY-MM-DD）"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                />
              </span>
            </>
          }
          headings={[
            "操作时间",
            "操作者",
            "操作类型",
            "操作对象",
            "结果",
            "操作",
          ]}
          render={(l) => (
            <tr key={l.id}>
              <td className="mono muted" data-label="操作时间">{date(l.occurred_at)}</td>
              <td data-label="操作者">{userName(l.actor)}</td>
              <td className="break" data-label="操作类型">
                {AUDIT_ACTION_LABEL[l.action] ?? l.action}
                <span className="mono muted" style={{ display: "block" }}>{l.action}</span>
              </td>
              <td className="break mono" data-label="操作对象">{l.target}</td>
              <td data-label="结果">
                <Status value={l.result} />
              </td>
              <td data-label="操作">{action("详情", () => open({ kind: "audit", audit: l }))}</td>
            </tr>
          )}
          />
        </div>
      </>
    );
  } else if (current === "resources") {
    content = (
      <>
        <div className="tabs">
          <button className={resourceTab === "usage" ? "active" : ""} onClick={() => setParams({ tab: "usage" })}>资源占用</button>
          <button className={resourceTab === "health" ? "active" : ""} onClick={() => setParams({ tab: "health" })}>健康状态</button>
        </div>
        {resourceTab === "health" ? (
          <>
            <div className="console-list">
              <Table
                headings={[
                  "服务 / 运行环境",
                  "类型",
                  "健康状态",
                  "最近检查",
                  "操作",
                ]}
                empty={!allRuntimes.length}
              >
                {allRuntimes.map((r) => (
                  <tr key={r.public_id}>
                    <td data-label="运行适配器">
                      <strong>{r.name}</strong>
                    </td>
                    <td data-label="驱动">{r.driver}</td>
                    <td data-label="健康状态">
                      <Status value={r.health_status} />
                    </td>
                    <td data-label="最近检查">{date(r.last_health_at)}</td>
                    <td data-label="操作">
                      {action("详情", () =>
                        open({ kind: "runtime", runtime: r }),
                      )}
                    </td>
                  </tr>
                ))}
              </Table>
            </div>
            {overview.data?.runtime?.error_code && <p role="alert">采集失败：{overview.data.runtime.error_code} · Trace：{overview.data.runtime.trace_id}</p>}
            {overview.data?.runtime?.drivers?.map((driver, index) => <p key={`${driver.code}-${index}`}>{driver.code} · {driver.driver} · {driver.status}{driver.error_code ? ` · ${driver.error_code}` : ""}</p>)}
            {overview.data?.alerts?.map((a) => (
              <div key={a.code} className="notice">
                {a.message}
              </div>
            ))}
          </>
        ) : (
          <>
            <div className="node-grid">
              {allRuntimes.map((r) => (
                <section key={r.public_id} className="panel">
                  <div className="panel-head">
                    <h2>{r.name}</h2>
                    <span className="mono muted">{r.code}</span>
                  </div>
                  <Meter
                    label="CPU 资源占用"
                    percent={usage(
                      r.capacity_cpu_millicores,
                      r.available_cpu_millicores,
                    )}
                    caption={`容量 ${r.capacity_cpu_millicores == null ? "—" : r.capacity_cpu_millicores / 1000} vCPU`}
                  />
                  <Meter
                    label="内存资源占用"
                    percent={usage(r.capacity_memory_mb, r.available_memory_mb)}
                    caption={`容量 ${r.capacity_memory_mb == null ? "—" : (r.capacity_memory_mb / 1024).toFixed(1)} GB`}
                  />
                  <p className="muted">磁盘占用：未提供</p>
                </section>
              ))}
            </div>

          </>
        )}
      </>
    );
  } else {
    content = (
      <>
        <section className="metrics">
          {[
            ["学生账号", people.students.length, "账号状态与课程关联"],
            ["教师账号", people.teachers.length, "教师负责课程内容"],
            [
              "平台课程",
              allCourses.length,
              `${allCourses.filter((c) => c.status === "PUBLISHED").length} 门进行中`,
            ],
            [
              "执行中作业",
              (overview.data?.runtime?.runs?.RUNNING ?? 0) + (overview.data?.runtime?.grades?.RUNNING ?? 0),
              "短生命周期运行与正式判题",
            ],
          ].map(([label, count, sub]) => (
            <div className="metric" key={label}>
              <span className="muted">{label}</span>
              <b>{count}</b>
              <small>{sub}</small>
            </div>
          ))}
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>需要处理</h2>
            <button className="link" onClick={() => go("logs")}>
              全部日志 →
            </button>
          </div>
          {issues.length ? (
            issues.map((issue) => (
              <div className="activity" key={issue.key}>
                <span className="muted">{issue.kind}</span>
                <span>
                  {issue.label}
                  {issue.detail ? <div className="muted break">{issue.detail}</div> : null}
                </span>
                <button className="link" onClick={issue.action}>
                  查看
                </button>
              </div>
            ))
          ) : (
            <p className="muted">当前没有需要处理的事项。</p>
          )}
        </section>
        <div className="grid">
          <section className="panel">
            <div className="panel-head">
              <h2>资源占用</h2>
              <button className="link" onClick={() => go("resources", "usage")}>
                查看资源 →
              </button>
            </div>
            {runtimes.isPending ? (
              <p className="muted">正在加载资源</p>
            ) : runtimes.error ? (
              <ErrorState error={runtimes.error} retry={refresh} />
            ) : !allRuntimes.length ? (
              <div className="empty">暂无运行环境</div>
            ) : (
              allRuntimes.map((r) => (
                <div className="overview-runtime" key={r.public_id}>
                  <div className="panel-head">
                    <strong>{r.name}</strong>
                    <span className="mono muted">{r.code}</span>
                  </div>
                  <Meter
                    label="CPU"
                    percent={usage(
                      r.capacity_cpu_millicores,
                      r.available_cpu_millicores,
                    )}
                  />
                  <Meter
                    label="内存"
                    percent={usage(r.capacity_memory_mb, r.available_memory_mb)}
                  />
                </div>
              ))
            )}
            <p className="muted">显示运行适配器配置的容量与可用量，不代表独立物理服务器或实时 CPU 利用率；历史采样尚未接入</p>
          </section>
          <section className="panel">
            <div className="panel-head">
              <h2>健康状态</h2>
              <button className="link" onClick={() => go("resources", "health")}>
                全部 →
              </button>
            </div>
            {allRuntimes.map((r) => (
              <div className="service-item" key={r.public_id}>
                <div>
                  {r.name}
                  <small>{r.driver}</small>
                </div>
                <Status value={r.health_status} />
              </div>
            ))}
            {!allRuntimes.length && <p className="muted">暂无健康数据</p>}
            <div className="service-item">
              <div>运行时引擎</div>
              <Status value={overview.data?.runtime?.status ?? "未接入监测"} />
            </div>
          </section>
        </div>
        <section className="panel">
          <div className="panel-head">
            <h2>近期管理操作</h2>
            <button className="link" onClick={() => go("logs")}>
              全部日志 →
            </button>
          </div>
          {audits.error ? (
            <ErrorState error={audits.error} retry={refresh} />
          ) : (
            allAudits.slice(0, 4).map((l) => (
              <div className="activity" key={l.id}>
                <span className="mono muted">{date(l.occurred_at)}</span>
                <span>
                  {l.action}
                  <div className="muted break">{l.target}</div>
                </span>
                <Status value={l.result} />
              </div>
            ))
          )}
          {!allAudits.length && !audits.error && (
            <p className="muted">暂无操作记录</p>
          )}
        </section>
        {overview.error && (
          <ErrorState error={overview.error} retry={refresh} />
        )}
      </>
    );
  }

  let modal: ReactNode = null;
  if (dialog) {
    let title = "",
      body: ReactNode,
      wide = true;
    if (dialog.kind === "person") {
      const u = dialog.account,
        owned = allCourses.filter((c) => c.owner_id === u.public_id);
      title = u.display_name;
      body = (
        <>
          <Fields
            values={[
              ["账号 ID", <span className="mono">{u.public_id}</span>],
              ["账号状态", <Status value={u.account_status} />],
              ["邮箱", u.email],
              ["用户名", u.username],
            ]}
          />
          {dialog.teacher ? (
            <>
              <h3>创建的课程 · {owned.length} 门</h3>
              {courses.error ? (
                <ErrorState error={courses.error} retry={refresh} />
              ) : (
                <Table
                  headings={["课程 / ID", "学生人数", "状态"]}
                  empty={!owned.length}
                >
                  {owned.map((c) => (
                    <tr key={c.public_id}>
                      <td data-label="课程">
                        {action(c.title, () =>
                          open({ kind: "course", course: c }),
                        )}
                        <div className="mono muted">{c.public_id}</div>
                      </td>
                      <td className="num" data-label="学生人数">{c.active_enrollment_count}</td>
                      <td data-label="状态">
                        <Status value={c.status} />
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </>
          ) : (
            <p className="muted">学生所在班级由任课教师维护；如需核对名单，请在「学生管理」里按班级查看</p>
          )}
        </>
      );
    } else if (dialog.kind === "account") {
      const u = dialog.account,
        disabling = u.account_status === "ACTIVE";
      title = `${disabling ? "禁用" : "恢复"}账号`;
      wide = false;
      body = (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            void mutate(
              () =>
                request(`/platform/users/${u.public_id}`, {
                  method: "PATCH",
                  ifMatch: String(u.row_version),
                  body: {
                    account_status: disabling ? "DISABLED" : "ACTIVE",
                    reason: String(data.get("reason")).trim(),
                  },
                }),
              disabling ? "账号已禁用" : "账号已恢复",
            );
          }}
        >
          <p>
            {u.display_name} <span className="mono muted">{u.public_id}</span>
          </p>
          <p className="muted">
            {disabling
              ? "禁用后账号无法正常使用平台，课程内容和成员关系保留"
              : "恢复后账号可重新正常使用平台"}
          </p>
          <label className="form-row">
            操作原因
            <textarea
              name="reason"
              required
              maxLength={500}
              defaultValue={disabling ? "" : "恢复账号使用"}
            />
          </label>
          <p className="form-error" role="alert">
            {error}
          </p>
          <div className="dialog-actions">
            <button type="button" disabled={busy} onClick={close}>
              取消
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "正在提交…" : disabling ? "确认禁用" : "确认恢复"}
            </button>
          </div>
        </form>
      );
    } else if (dialog.kind === "course") {
      const c = dialog.course;
      title = c.title;
      body = (
        <>
          <p className="mono muted">{c.public_id} · 一门课程 / 一个教学班</p>
          <div className="tabs">
            {[
              ["info", "课程信息"],
              ["members", "学生名单"],
              ["experiments", "实验安排"],
            ].map(([key, label]) => (
              <button
                key={key}
                className={courseTab === key ? "active" : ""}
                onClick={() => setCourseTab(key ?? "info")}
              >
                {label}
              </button>
            ))}
          </div>
          {courseTab === "info" ? (
            <>
              <Fields
                values={[
                  ["课程 ID", <span className="mono">{c.public_id}</span>],
                  ["课程状态", <Status value={c.status} />],
                  ["任课教师", c.owner_name],
                  ["学生人数", `${c.active_enrollment_count} 人`],
                  ["教学开始", date(c.teaching_start)],
                  ["教学结束", date(c.teaching_end)],
                ]}
              />
              <p>{c.summary || "暂无课程介绍"}</p>
            </>
          ) : (
            <div className="empty">
              {courseTab === "members" ? "课程学生名单" : "课程实验安排"}
              由任课教师维护；如需修改名单，请联系课程教师
            </div>
          )}
        </>
      );
    } else if (dialog.kind === "image-form") {
      title = "新增镜像";
      wide = false;
      body = (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            try {
              const address = imageAddress(String(data.get("address")));
              if (
                allImages.some(
                  (i) =>
                    i.registry === address.registry &&
                    i.repository === address.repository &&
                    i.display_tag === String(data.get("version")).trim(),
                )
              ) {
                setError("相同镜像地址和版本已存在");
                return;
              }
              const key = crypto.randomUUID();
              void mutate(
                () =>
                  request(imagesPath, {
                    method: "POST",
                    idempotencyKey: key,
                    body: {
                      ...address,
                      display_name: String(data.get("display_name")).trim(),
                      display_tag: String(data.get("version")).trim(),
                      risk_level: "LOW",
                      reason: String(data.get("reason")).trim(),
                    },
                  }),
                "镜像已登记，完成摘要解析与检查后可启用",
              );
            } catch (cause) {
              setError(cause instanceof Error ? cause.message : "镜像地址无效");
            }
          }}
        >
          <label className="form-row">
            显示名称
            <input
              name="display_name"
              maxLength={120}
              placeholder="例如：编程运行环境（可选）"
            />
          </label>
          <label className="form-row">
            镜像地址
            <input
              name="address"
              required
              maxLength={500}
              placeholder="registry.example.edu/labs/linux"
            />
          </label>
          <label className="form-row">
            版本
            <input name="version" required maxLength={128} placeholder="v2.4" />
          </label>
          <label className="form-row">
            登记原因
            <textarea name="reason" required maxLength={500} />
          </label>
          <p className="muted">
            新镜像登记后处于待就绪状态，不会自动开放给教师
          </p>
          <p role="alert" className="form-error">
            {error}
          </p>
          <div className="dialog-actions">
            <button type="button" disabled={busy} onClick={close}>
              取消
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "保存中…" : "保存镜像"}
            </button>
          </div>
        </form>
      );
    } else if (dialog.kind === "image-toggle") {
      const i = dialog.image,
        disabling = i.approval_status === "APPROVED",
        ready = !!i.digest && i.scan_status === "CLEAN";
      title = disabling ? "停用镜像" : "启用镜像";
      wide = false;
      body = (
        <>
          <p>{i.repository}</p>
          <p className="mono break">
            {i.registry}/{i.repository}:{i.display_tag}
          </p>
          <p className="muted">
            {disabling
              ? "停用后禁止新选用，保留已有实验关联"
              : ready
                ? "启用后教师可以在实验中选择此镜像"
                : "该镜像尚未完成摘要解析或未通过扫描，暂不能启用"}
          </p>
          <p className="form-error" role="alert">
            {error}
          </p>
          <div className="dialog-actions">
            <button disabled={busy} onClick={close}>
              取消
            </button>
            <button
              className="primary"
              disabled={busy || (!disabling && !ready)}
              onClick={() =>
                void mutate(
                  () =>
                    request(`${imagesPath}/${i.public_id}/decide`, {
                      method: "POST",
                      ifMatch: String(i.row_version),
                      idempotencyKey: crypto.randomUUID(),
                      body: {
                        decision: disabling ? "RETIRED" : "APPROVED",
                        reason: disabling
                          ? "管理员停用镜像，保留已有实验关联"
                          : "管理员启用镜像",
                      },
                    }),
                  disabling ? "镜像已停用" : "镜像已启用",
                )
              }
            >
              {busy ? "正在提交…" : disabling ? "确认停用" : "确认启用"}
            </button>
          </div>
        </>
      );
    } else if (dialog.kind === "image-rename") {
      const i = dialog.image;
      title = "修改镜像名称";
      wide = false;
      body = (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const displayName = String(data.get("display_name")).trim();
            if (!displayName) {
              setError("请填写显示名称");
              return;
            }
            void mutate(
              () =>
                request(`${imagesPath}/${i.public_id}/rename`, {
                  method: "POST",
                  idempotencyKey: crypto.randomUUID(),
                  ifMatch: String(i.row_version),
                  body: {
                    display_name: displayName,
                    reason: String(data.get("reason")).trim(),
                  },
                }),
              "镜像名称已更新",
            );
          }}
        >
          <p className="mono break">
            {i.registry}/{i.repository}
          </p>
          <label className="form-row">
            显示名称
            <input
              name="display_name"
              required
              maxLength={120}
              defaultValue={i.display_name ?? ""}
              placeholder="例如：编程运行环境"
            />
          </label>
          <label className="form-row">
            变更原因
            <textarea name="reason" maxLength={500} />
          </label>
          <p role="alert" className="form-error">
            {error}
          </p>
          <div className="dialog-actions">
            <button type="button" disabled={busy} onClick={close}>
              取消
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "保存中…" : "保存名称"}
            </button>
          </div>
        </form>
      );
    } else if (dialog.kind === "image") {
      const i = dialog.image;
      title = i.display_name || i.repository;
      body = (
        <>
          <Fields
            values={[
              ["显示名称", i.display_name || "未设置"],
              ["镜像 ID", i.public_id],
              ["使用状态", <Status value={i.approval_status} />],
              [
                "镜像地址",
                <span className="mono">
                  {i.registry}/{i.repository}
                </span>,
              ],
              ["版本", i.display_tag || "—"],
              ["扫描状态", <Status value={i.scan_status} />],
              [
                "Digest",
                <span className="mono">{i.digest || "尚未解析"}</span>,
              ],
            ]}
          />
          <p className="muted">
            显示名称只影响管理端展示；镜像地址、Digest 与审批状态由系统维护
          </p>
          <p className="form-error">{error}</p>
          {!i.digest && (
            <button
              disabled={busy}
              onClick={() => {
                const key = crypto.randomUUID();
                void mutate(
                  () =>
                    request(`${imagesPath}/${i.public_id}/resolve`, {
                      method: "POST",
                      body: {},
                      ifMatch: String(i.row_version),
                      idempotencyKey: key,
                    }),
                  "已提交镜像摘要解析任务，请稍后刷新",
                );
              }}
            >
              解析镜像摘要
            </button>
          )}
        </>
      );
    } else if (dialog.kind === "profile-form") {
      title = "新增资源规格";
      wide = false;
      body = (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const cpu = Math.round(Number(data.get("cpu")) * 1000);
            const memory = Math.round(Number(data.get("memory")));
            const disk = Math.round(Number(data.get("disk")));
            if (
              !Number.isFinite(cpu) ||
              cpu < 100 ||
              !Number.isFinite(memory) ||
              memory < 64 ||
              !Number.isFinite(disk) ||
              disk < 1
            ) {
              setError("CPU 至少 0.1 核、内存至少 64 MB、磁盘至少 1 GB");
              return;
            }
            void mutate(
              () =>
                request(profilesPath, {
                  method: "POST",
                  idempotencyKey: crypto.randomUUID(),
                  body: {
                    code: String(data.get("code")).trim(),
                    name: String(data.get("name")).trim(),
                    runtime_type: "CONTAINER",
                    cpu_millicores: cpu,
                    memory_mb: memory,
                    cpu_request_millicores: Math.max(Math.floor(cpu / 2), 1),
                    cpu_limit_millicores: cpu * 2,
                    memory_request_mb: Math.max(Math.floor(memory / 2), 1),
                    memory_limit_mb: memory * 2,
                    disk_gb: disk,
                    network_mode: "DENY_ALL",
                    cost_minor_per_hour: 0,
                    currency_code: "CNY",
                    reason: String(data.get("reason")).trim(),
                  },
                }),
              "资源规格已创建，教师可以立即选用",
            );
          }}
        >
          <label className="form-row">
            规格名称
            <input
              name="name"
              required
              maxLength={120}
              placeholder="例如：标准 0.5 核 / 512 MB"
            />
          </label>
          <label className="form-row">
            规格编码
            <input
              name="code"
              required
              maxLength={64}
              pattern="[A-Za-z0-9_-]+"
              placeholder="STD-512M"
            />
          </label>
          <label className="form-row">
            CPU（核）
            <input
              name="cpu"
              type="number"
              required
              min="0.1"
              step="0.05"
              defaultValue="0.5"
            />
          </label>
          <label className="form-row">
            内存（MB）
            <input
              name="memory"
              type="number"
              required
              min="64"
              step="64"
              defaultValue="512"
            />
          </label>
          <label className="form-row">
            磁盘（GB）
            <input
              name="disk"
              type="number"
              required
              min="1"
              step="1"
              defaultValue="2"
            />
          </label>
          <label className="form-row">
            变更原因
            <textarea name="reason" required maxLength={500} />
          </label>
          <p className="muted">
            请求量与上限按 CPU、内存的 50% / 200% 自动生成；网络固定禁止外联
          </p>
          <p role="alert" className="form-error">
            {error}
          </p>
          <div className="dialog-actions">
            <button type="button" disabled={busy} onClick={close}>
              取消
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "保存中…" : "保存规格"}
            </button>
          </div>
        </form>
      );
    } else if (dialog.kind === "profile-toggle") {
      const p = dialog.profile,
        disabling = p.status === "ACTIVE";
      title = disabling ? "停用资源规格" : "启用资源规格";
      body = (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const reason = String(
              new FormData(e.currentTarget).get("reason"),
            ).trim();
            void mutate(
              () =>
                request(
                  `${profilesPath}/${p.public_id}/${disabling ? "retire" : "activate"}`,
                  {
                    method: "POST",
                    idempotencyKey: crypto.randomUUID(),
                    ifMatch: p.row_version,
                    body: { reason },
                  },
                ),
              disabling ? "资源规格已停用" : "资源规格已启用",
            );
          }}
        >
          <p>
            <strong>{p.name}</strong>
          </p>
          <p className="mono break">
            {p.code} · {formatCores(p.cpu_millicores)} 核 /{" "}
            {formatMemory(p.memory_mb)}
          </p>
          <p className="muted">
            {disabling
              ? "停用后教师不能再选到这一档；已保存的版本保持原样，不会被改写。"
              : "启用后教师可以在判题资源里选择这一档。"}
          </p>
          <label className="form-row">
            变更原因
            <textarea name="reason" required maxLength={500} />
          </label>
          <p role="alert" className="form-error">
            {error}
          </p>
          <div className="dialog-actions">
            <button type="button" disabled={busy} onClick={close}>
              取消
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "提交中…" : disabling ? "停用规格" : "启用规格"}
            </button>
          </div>
        </form>
      );
    } else if (dialog.kind === "profile") {
      const p = dialog.profile;
      title = p.name;
      body = (
        <Fields
          values={[
            ["规格 ID", <span className="mono">{p.public_id}</span>],
            ["编码", p.code],
            ["状态", <Status value={p.status} />],
            ["CPU", `${formatCores(p.cpu_millicores)} 核`],
            ["内存", formatMemory(p.memory_mb)],
            ["磁盘", `${p.disk_gb} GB`],
            ["网络", p.network_mode === "DENY_ALL" ? "禁止外联" : p.network_mode],
            ["类型", p.runtime_type === "CONTAINER" ? "容器" : p.runtime_type],
          ]}
        />
      );
    } else if (dialog.kind === "runtime") {
      const r = dialog.runtime;
      title = r.name;
      body = (
        <Fields
          values={[
            ["运行环境 ID", r.public_id],
            ["驱动", r.driver],
            ["健康状态", <Status value={r.health_status} />],
            ["最近检查", date(r.last_health_at)],
            [
              "CPU 占用",
              usage(r.capacity_cpu_millicores, r.available_cpu_millicores) ==
              null
                ? "未提供"
                : `${usage(r.capacity_cpu_millicores, r.available_cpu_millicores)}%`,
            ],
            [
              "内存占用",
              usage(r.capacity_memory_mb, r.available_memory_mb) == null
                ? "未提供"
                : `${usage(r.capacity_memory_mb, r.available_memory_mb)}%`,
            ],
          ]}
        />
      );
    } else {
      const l = dialog.audit;
      title = "操作详情";
      body = (
        <>
          <Fields
            values={[
              ["操作时间", date(l.occurred_at)],
              ["操作者", userName(l.actor)],
              ["操作类型", l.action],
              ["结果", <Status value={l.result} />],
              ["操作对象", l.target],
              ["Trace ID", <span className="mono">{l.trace_id || "—"}</span>],
            ]}
          />
          <p className="muted">
            审计记录只保留结果与 Trace ID；排查时请把上面的 Trace ID 提供给平台开发
          </p>
        </>
      );
    }
    modal = (
      <Modal title={title} wide={wide} onClose={close} busy={busy}>
        {body}
      </Modal>
    );
  }
  const updated = Math.max(...required.map((q) => q.dataUpdatedAt));
  return (
    <>
      <nav className="crumb" aria-label="面包屑">
        <span>管理控制台{"　/　"}</span>
        <b>{names[current]}</b>
      </nav>
      <div className="heading">
        <div>
          <h1>{names[current]}</h1>
          {descriptions[current] ? <div className="subtitle">{descriptions[current]}</div> : null}
        </div>
        {current === "images" || current === "profiles" ? (
          <button
            className="primary"
            disabled={
              current === "images"
                ? images.isPending || images.isError
                : profiles.isPending || profiles.isError
            }
            onClick={() =>
              open({ kind: current === "images" ? "image-form" : "profile-form" })
            }
          >
            {current === "images" ? "新增镜像" : "新增规格"}
          </button>
        ) : (
          <button onClick={refresh}>
            刷新{current === "resources" ? "状态" : "数据"}
          </button>
        )}
      </div>
      {toast && (
        <div className="console-feedback" role="status">
          {toast}
          <button
            className="link"
            aria-label="关闭操作反馈"
            onClick={() => setToast("")}
          >
            关闭
          </button>
        </div>
      )}
      {!dialog && error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {content}
      {current === "overview" ? (
        <div className="footer-note">
          数据更新时间：{updated ? date(new Date(updated).toISOString()) : "—"} · 读取平台实际数据
        </div>
      ) : null}
      {modal}
      {recentAuth.dialog}
    </>
  );
}


