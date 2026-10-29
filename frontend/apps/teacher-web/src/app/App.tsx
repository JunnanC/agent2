import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { configureRequestHooks } from "@edu/auth-client";
import { teachingApi } from "@edu/api-client";
import { EmptyState, LoadingState } from "@edu/ui";
import { AppProviders, queryClient } from "./providers";
import { keys } from "@edu/query-keys";
import { AuthGuard, PortalSSEBridge } from "./guards";
import { Login } from "@/pages/login";
import { Home } from "@/pages/home";
import { Courses } from "@/pages/courses";
import { Enrollments } from "@/pages/enrollments";
import { Templates } from "@/pages/templates";
import { TemplateEditor } from "@/pages/template-editor";
import { Publishing } from "@/pages/publishing";
import { Students } from "@/pages/students";
import { Reviews } from "@/pages/reviews";
import { Analytics } from "@/pages/analytics";

export function App(): JSX.Element {
  return (
    <AppProviders>
      <BrowserRouter>
        <RequestHookBridge />
        <PortalSSEBridge />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<AuthGuard />}>
            <Route path="/" element={<Home />} />
            <Route path="/courses" element={<Courses />} />
            <Route path="/courses/:courseId/enrollments" element={<Enrollments />} />
            <Route path="/courses/:courseId/templates" element={<Templates />} />
            <Route path="/courses/:courseId/templates/:templateId/edit" element={<TemplateEditor />} />
            <Route path="/courses/:courseId/publishing" element={<Publishing />} />
            <Route path="/courses/:courseId/students" element={<Students />} />
            <Route path="/courses/:courseId/reviews" element={<Reviews />} />
            <Route path="/courses/:courseId/analytics" element={<Analytics />} />
            {/*
              顶层入口别名：导航栏中的扁平入口不再依赖具体课程 ID，
              由 CourseGate 跳转到第一门课程的对应工作页
            */}
            <Route path="/enrollments" element={<CourseGate section="enrollments" />} />
            <Route path="/templates" element={<CourseGate section="templates" />} />
            <Route path="/publishing" element={<CourseGate section="publishing" />} />
            <Route path="/students" element={<CourseGate section="students" />} />
            <Route path="/reviews" element={<CourseGate section="reviews" />} />
            <Route path="/analytics" element={<CourseGate section="analytics" />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AppProviders>
  );
}

/**
 * 顶层入口 → 第一门课程的对应页面跳转。
 * 没有课程时给出明确的下一步（先创建课程），而不是静默白屏。
 */
function CourseGate({ section }: { section: string }): JSX.Element {
  const courses = useQuery({ queryKey: keys.teachingCourses(), queryFn: () => teachingApi.courses({ page_size: 1 }) });
  if (courses.isPending) return <div className="app-shell"><LoadingState label="正在定位课程" /></div>;
  const first = courses.data?.rows[0];
  if (first) {
    return <Navigate to={`/courses/${first.public_id}/${section}`} replace />;
  }
  return (
    <div className="app-shell">
      <EmptyState
        title="还没有授课课程"
        hint={`使用「${section}」前需要先创建课程。`}
        action={<a className="btn primary" href="/courses">前往我的课程创建</a>}
      />
    </div>
  );
}

function RequestHookBridge(): null {
  const navigate = useNavigate();
  useEffect(() => {
    configureRequestHooks({
      onAuthExpired: () => {
        queryClient.clear();
        navigate("/login", { replace: true });
      },
    });
  }, [navigate]);
  return null;
}

export function FullPageLoading(): JSX.Element {
  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "60vh", padding: 40 }}>
      <LoadingState label="正在载入教师门户" />
    </div>
  );
}
