import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { configureRequestHooks } from "@edu/auth-client";
import { LoadingState, ToastProvider } from "@edu/ui";
import { queryClient } from "./providers";
import { AuthGuard, PortalSSEBridge } from "./guards";
import { Login } from "@/pages/login";
import { Home } from "@/pages/home";
import { Users } from "@/pages/users";
import { Governance } from "@/pages/governance";
import { Resources } from "@/pages/resources";
import { Incidents } from "@/pages/incidents";
import { Audit } from "@/pages/audit";
import { Agents } from "@/pages/agents";

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
              <Route path="/users" element={<Users />} />
              <Route path="/governance" element={<Governance />} />
              <Route path="/resources" element={<Resources />} />
              <Route path="/incidents" element={<Incidents />} />
              <Route path="/audit" element={<Audit />} />
              <Route path="/agents" element={<Agents />} />
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
    <div style={{ display: "grid", placeItems: "center", minHeight: "60vh", padding: 40 }}>
      <LoadingState label="正在载入平台管理门户" />
    </div>
  );
}
