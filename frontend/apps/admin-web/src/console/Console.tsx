import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { request, ApiError } from "@edu/auth-client";
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
  type Instance,
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
  resources: "服务与资源",
  logs: "操作日志",
};
type Page = keyof typeof names;
const glyphs: Record<Page, string> = {
  overview: "M3 3h6v6H3zM13 3h6v6h-6zM3 13h6v6H3zM13 13h6v6h-6z",
  courses: "M3 4h7l2 2 2-2h7v15h-7l-2 2-2-2H3zM12 6v15",
  students:
    "M8 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM1 21v-3a7 7 0 0 1 14 0v3M16 4a4 4 0 0 1 0 8M18 15a6 6 0 0 1 5 6",
  teachers: "M12 3 1 8l11 5 11-5-11-5zM5 10v7c4 4 10 4 14 0v-7M23 8v9",
  images: "m12 2 10 5v10l-10 5L2 17V7l10-5zM2 7l10 5 10-5M12 12v10",
  resources: "M3 3h18v7H3zM3 14h18v7H3zM6 6h1M6 17h1M11 6h7M11 17h7",
  logs: "M5 3h14v19H5zM9 8h6M9 12h6M9 16h4",
};
const descriptions: Record<Page, string> = {
  overview: "关注教学实验的运行情况与需要处理的问题",
  courses: "每门课程对应一个教学班，教学内容与学生名单由任课教师维护",
  students: "查看学生账号，管理账号使用状态",
  teachers: "查看教师及所建课程，管理账号使用状态",
  images: "统一维护教师可选用的实验镜像",
  resources: "查看服务健康与实验资源占用，不提供运行控制操作",
  logs: "追踪账号、课程及镜像的管理操作",
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
  runtimesPath = "/platform/runtime-adapters",
  instancesPath = "/platform/instances",
  logsPath = "/platform/operations/audit";
const accountStates: [string, string][] = [
  ["ACTIVE", "正常"],
  ["DISABLED", "已禁用"],
];
type Dialog =
  | { kind: "account"; account: Account }
  | { kind: "person"; account: Account; teacher: boolean }
  | { kind: "course"; course: Course }
  | { kind: "image"; image: Image }
  | { kind: "image-form" }
  | { kind: "image-toggle"; image: Image }
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
  const [menu, setMenu] = useState(false);
  useEffect(() => {
    document.title = names[current] + " · 教学实验平台管理";
  }, [current]);
  function go(page: Page) {
    navigate(page === "overview" ? "/" : `/${page}`);
    setMenu(false);
  }
  return (
    <div className="admin-console">
      <a className="console-skip" href="#console-main">
        跳到主要内容
      </a>
      {menu && (
        <button
          className="console-backdrop"
          aria-label="关闭导航"
          onClick={() => setMenu(false)}
        />
      )}
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <div className="brand">
          <svg
            viewBox="0 0 28 28"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden="true"
          >
            <path d="M4 5h8v18H4zM16 5h8v18h-8zM8 9v10M20 9v10M12 14h4" />
          </svg>
          <div>
            教学实验平台<small>运维管理控制台</small>
          </div>
        </div>
        <div className="nav-label">平台管理</div>
        <nav className="nav" aria-label="平台管理">
          {(Object.keys(names) as Page[]).map((key) => (
            <button
              key={key}
              className={current === key ? "active" : ""}
              aria-current={current === key ? "page" : undefined}
              onClick={() => go(key)}
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path d={glyphs[key]} />
              </svg>
              {names[key]}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="scope">平台范围 · 全部课程</div>运维管理员
          <br />
          服务与资源仅供查看
        </div>
      </aside>
      <header className="topbar">
        <div>
          <button
            className="mobile-menu"
            aria-label="切换导航"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            菜单
          </button>
          <span className="desktop">管理控制台</span>
          <span>/ {names[current]}</span>
        </div>
        <div>
          <span className="avatar">
            {session.me?.display_name?.slice(0, 1) || "运"}
          </span>
          <span className="desktop">
            {session.me?.display_name || "运维管理员"}
          </span>
          <button
            className="link"
            onClick={() =>
              void session.logout().then(() => {
                client.clear();
                navigate("/login");
              })
            }
          >
            退出
          </button>
        </div>
      </header>
      <main id="console-main" className="sheet" tabIndex={-1}>
        <PageContent key={current} current={current} go={go} />
      </main>
    </div>
  );
}

function PageContent({
  current,
  go,
}: {
  current: Page;
  go: (page: Page) => void;
}) {
  const client = useQueryClient(),
    recentAuth = useRecentAuthGuard();
  const [dialog, setDialog] = useState<Dialog | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [toast, setToast] = useState("");
  const [resourceTab, setResourceTab] = useState("services"),
    [courseTab, setCourseTab] = useState("info"),
    [from, setFrom] = useState(""),
    [to, setTo] = useState("");
  const users = useList<Account>(accountsPath),
    roles = useList<Role>(rolesPath),
    admins = useList<Role>(adminsPath),
    courses = useList<Course>(coursesPath);
  const images = useList<Image>(imagesPath),
    runtimes = useList<Runtime>(runtimesPath),
    instances = useList<Instance>(instancesPath),
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
    allImages = images.data ?? [],
    allRuntimes = runtimes.data ?? [],
    allInstances = instances.data ?? [],
    allAudits = audits.data ?? [];
  const userName = (id: string) =>
    users.data?.find((u) => u.public_id === id)?.display_name ?? id;
  const findCourse = (id: string) => allCourses.find((c) => c.public_id === id);
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
      ? [users, roles, admins, ...(current === "students" ? [] : [courses])]
      : current === "courses"
        ? [courses]
        : current === "images"
          ? [images]
          : current === "logs"
            ? [audits]
            : [runtimes, instances, overview];
  const failure = required.find((q) => q.error);
  let content: ReactNode;
  if (failure) content = <ErrorState error={failure.error} retry={refresh} />;
  else if (required.some((q) => q.isPending))
    content = (
      <div className="empty" role="status">
        正在加载{names[current]}
      </div>
    );
  else if (current === "students" || current === "teachers") {
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
            <td>
              <strong>{u.display_name}</strong>
              <span className="mono muted">{u.public_id}</span>
            </td>
            <td>{u.email}</td>
            {isTeacher && (
              <td className="num">
                {allCourses.filter((c) => c.owner_id === u.public_id).length}
              </td>
            )}
            <td>
              <Status value={u.account_status} />
            </td>
            <td className="actions">
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
                  PUBLISHED: "进行中",
                  DRAFT: "草稿",
                  CLOSED: "已结束",
                  ARCHIVED: "已归档",
                }[s]!,
              ] as [string, string],
          )}
          state={(c) => c.status}
          placeholder="搜索课程名称、ID 或教师"
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
              <td>
                <strong>{c.title}</strong>
                <span className="mono muted">{c.public_id}</span>
              </td>
              <td>{c.owner_name}</td>
              <td className="num">{c.active_enrollment_count}</td>
              <td>
                <Status value={c.status} />
              </td>
              <td className="mono muted">{date(c.teaching_start)}</td>
              <td className="actions">
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
        <p className="footer-note">课程下架能力尚未开放，当前只提供课程查询</p>
      </>
    );
  } else if (current === "images") {
    content = (
      <>
        <div className="notice">
          <span>
            教师仅能使用已启用且已通过检查的镜像，停用不删除已有实验关联
          </span>
        </div>
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
                  APPROVED: "启用",
                  RETIRED: "停用",
                  PENDING: "待就绪",
                  REJECTED: "未启用",
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
              <td>
                <strong>{i.repository.split("/").at(-1)}</strong>
                <span className="mono muted">{i.public_id}</span>
              </td>
              <td>
                <div className="mono break">
                  {i.registry}/{i.repository}
                </div>
                <span className="mono muted">{i.display_tag || "—"}</span>
              </td>
              <td>
                <Status value={i.scan_status} />
              </td>
              <td>
                <Status value={i.approval_status} />
              </td>
              <td className="actions">
                {action("详情", () => open({ kind: "image", image: i }))}
                <button
                  className="link"
                  disabled
                  title="后端不支持修改镜像名称、用途或地址"
                >
                  编辑
                </button>
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
  } else if (current === "logs") {
    const data = allAudits.filter(
      (l) =>
        (!from ||
          new Date(l.occurred_at).toLocaleDateString("sv-SE", {
            timeZone: "Asia/Shanghai",
          }) >= from) &&
        (!to ||
          new Date(l.occurred_at).toLocaleDateString("sv-SE", {
            timeZone: "Asia/Shanghai",
          }) <= to),
    );
    content = (
      <List
        rows={data}
        text={(l) => `${l.action} ${l.target} ${l.actor} ${l.trace_id}`}
        states={[...new Set(allAudits.map((l) => l.action))].map((s) => [s, s])}
        state={(l) => l.action}
        placeholder="搜索操作、对象或操作者"
        extra={
          <>
            <input
              type="date"
              aria-label="开始日期"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
            <span className="muted">至</span>
            <input
              type="date"
              aria-label="结束日期"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
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
            <td className="mono muted">{date(l.occurred_at)}</td>
            <td>{userName(l.actor)}</td>
            <td className="break">{l.action}</td>
            <td className="break mono">{l.target}</td>
            <td>
              <Status value={l.result} />
            </td>
            <td>{action("详情", () => open({ kind: "audit", audit: l }))}</td>
          </tr>
        )}
      />
    );
  } else if (current === "resources") {
    content = (
      <>
        <div className="tabs">
          <button
            className={resourceTab === "services" ? "active" : ""}
            onClick={() => setResourceTab("services")}
          >
            服务状态
          </button>
          <button
            className={resourceTab === "nodes" ? "active" : ""}
            onClick={() => setResourceTab("nodes")}
          >
            资源占用
          </button>
        </div>
        {resourceTab === "services" ? (
          <>
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
                  <td>
                    <strong>{r.name}</strong>
                    <span className="mono muted">{r.code}</span>
                  </td>
                  <td>{r.driver}</td>
                  <td>
                    <Status value={r.health_status} />
                  </td>
                  <td>{date(r.last_health_at)}</td>
                  <td>
                    {action("详情", () =>
                      open({ kind: "runtime", runtime: r }),
                    )}
                  </td>
                </tr>
              ))}
            </Table>
            <p className="footer-note">
              当前展示运行时健康；数据库、缓存等服务的独立健康检查尚未接入
            </p>
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
            <h3>实验实例 · {allInstances.length} 个</h3>
            <List
              rows={allInstances}
              text={(i) =>
                `${i.public_id} ${i.course_id} ${i.student_id} ${i.runtime_driver}`
              }
              states={[...new Set(allInstances.map((i) => i.status))].map(
                (s) => [s, s],
              )}
              state={(i) => i.status}
              placeholder="搜索实例、课程或学生 ID"
              headings={["实例 ID", "课程", "学生", "运行驱动", "状态"]}
              render={(i) => (
                <tr key={i.public_id}>
                  <td className="mono">{i.public_id}</td>
                  <td>
                    {findCourse(i.course_id)
                      ? action(findCourse(i.course_id)!.title, () =>
                          open({
                            kind: "course",
                            course: findCourse(i.course_id)!,
                          }),
                        )
                      : i.course_id}
                    <div className="mono muted">{i.course_id}</div>
                  </td>
                  <td>{userName(i.student_id)}</td>
                  <td>{i.runtime_driver}</td>
                  <td>
                    <Status value={i.status} />
                  </td>
                </tr>
              )}
            />
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
              "运行实例",
              instances.data
                ? allInstances.filter(
                    (i) => !["DESTROYED", "FAILED"].includes(i.status),
                  ).length
                : "—",
              "来自运行实例记录",
            ],
          ].map(([label, count, sub]) => (
            <div className="metric" key={label}>
              <span className="muted">{label}</span>
              <b>{count}</b>
              <small>{sub}</small>
            </div>
          ))}
        </section>
        {overview.data?.alerts?.length ? (
          <div className="notice">
            <span>{overview.data.alerts[0]?.message}</span>
            <button className="link" onClick={() => go("resources")}>
              查看详情
            </button>
          </div>
        ) : null}
        <div className="grid">
          <section className="panel">
            <div className="panel-head">
              <h2>实验运行环境资源占用</h2>
              <button className="link" onClick={() => go("resources")}>
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
            <p className="muted">展示当前资源快照，历史使用率采样尚未接入</p>
          </section>
          <section className="panel">
            <div className="panel-head">
              <h2>运行环境健康</h2>
              <button className="link" onClick={() => go("resources")}>
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
              <Status value={overview.data?.runtime?.status} />
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
                      <td>
                        {action(c.title, () =>
                          open({ kind: "course", course: c }),
                        )}
                        <div className="mono muted">{c.public_id}</div>
                      </td>
                      <td className="num">{c.active_enrollment_count}</td>
                      <td>
                        <Status value={c.status} />
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </>
          ) : (
            <p className="muted">管理端尚未提供该学生的课程成员关系查询</p>
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
              由教师管理，管理端查询接口尚未开放
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
          <p className="muted">
            镜像名称暂取仓库路径末段，独立显示名称和用途说明尚未支持保存
          </p>
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
        ready = !!i.digest && i.scan_status === "CLEAN",
        key = crypto.randomUUID();
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
                      idempotencyKey: key,
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
    } else if (dialog.kind === "image") {
      const i = dialog.image;
      title = i.repository;
      body = (
        <>
          <Fields
            values={[
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
          <p className="muted">独立显示名称、用途说明及课程引用关系尚未提供</p>
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
            完整原因及变更前后数据尚未通过审计查询接口提供
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
      <div className="heading">
        <div>
          <h1>{names[current]}</h1>
          <div className="subtitle">{descriptions[current]}</div>
        </div>
        {current === "images" ? (
          <button
            className="primary"
            disabled={images.isPending || images.isError}
            onClick={() => open({ kind: "image-form" })}
          >
            新增镜像
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
      <div className="footer-note">
        数据更新时间：{updated ? date(new Date(updated).toISOString()) : "—"}
        （北京时间） · 读取平台实际数据
      </div>
      {modal}
      {recentAuth.dialog}
    </>
  );
}
