import { useEffect } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { configureRequestHooks } from "@edu/auth-client";
import { LoadingState, ToastProvider } from "@edu/ui";
import { queryClient } from "./providers";
import { AuthGuard, PortalSSEBridge } from "./guards";
import { Login } from "@/pages/login";
import { Home } from "@/pages/home";
import { Courses } from "@/pages/courses";
import { JoinCourses } from "@/pages/join-courses";
import { CourseDetail } from "@/pages/course-detail";
import { Experiments } from "@/pages/experiments";
import { TaskDetail } from "@/pages/task-detail";
import { Workbench } from "@/pages/workbench";
import { Notifications } from "@/pages/notifications";
import { Profile } from "@/pages/profile";
import { NoAccess } from "@/pages/no-access";

export function App(): JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <RequestHookBridge />
          <PortalSSEBridge />
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<AuthGuard />}>
              <Route path="/" element={<Home />} />
              <Route path="/courses" element={<Courses />} />
              <Route path="/courses/join" element={<JoinCourses />} />
              <Route path="/courses/:courseId" element={<CourseDetail />} />
              <Route path="/courses/:courseId/questions" element={<CourseDetail discussionPage />} />
              <Route path="/experiments" element={<Experiments />} />
              <Route path="/experiments/:taskId" element={<TaskDetail />} />
              <Route path="/notifications" element={<Notifications />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/no-access" element={<NoAccess />} />
            </Route>
            <Route element={<AuthGuard fullscreen />}>
              <Route path="/experiments/:taskId/workbench" element={<Workbench />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
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
    <div style={{ display: "grid", placeItems: "center", minHeight: "60vh" }}>
      <LoadingState label="正在载入学生门户" />
    </div>
  );
}
