import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fetchMe } from "@/lib/auth";
import { useAuthStore } from "@/app/stores/authStore";
import { AppLayout } from "@/components/layout/AppLayout";
import { LoginPage } from "@/pages/LoginPage";
import { QAPage } from "@/pages/QAPage";
import { TrainingPage } from "@/pages/TrainingPage";
import { TrainingManagePage } from "@/pages/TrainingManagePage";
import { DeviationPage } from "@/pages/DeviationPage";
import { ChangePage } from "@/pages/ChangePage";
import { AuditPage } from "@/pages/AuditPage";
import { SaePage } from "@/pages/SaePage";
import { KbPage } from "@/pages/KbPage";
import { SystemPage } from "@/pages/SystemPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
  },
});

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading, setUser, setLoading } = useAuthStore();
  const [done, setDone] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("pharmareg_token");
    if (!token) {
      setLoading(false);
      setDone(true);
      return;
    }
    fetchMe()
      .then((u) => setUser(u))
      .catch(() => setUser(null))
      .finally(() => {
        setLoading(false);
        setDone(true);
      });
  }, [setUser, setLoading]);

  if (!done || loading) {
    return <div style={{ padding: "4rem", textAlign: "center", color: "var(--color-muted)" }}>加载中…</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

// 方案A：培训认证中心考生角色白名单（与导航过滤一致）
const EXAM_TAKER_ROLES = ["operator", "crc"];

function RequireRole({ roles, children }: { roles: string[]; children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!user || !roles.some((r) => user.roles.includes(r))) {
    return <Navigate to="/qa" replace />;
  }
  return <>{children}</>;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="/qa" replace />} />
            <Route path="qa" element={<QAPage />} />
            <Route
              path="training"
              element={
                <RequireRole roles={EXAM_TAKER_ROLES}>
                  <TrainingPage />
                </RequireRole>
              }
            />
            <Route
              path="training/manage"
              element={
                <RequireRole roles={["trainer", "admin"]}>
                  <TrainingManagePage />
                </RequireRole>
              }
            />
            <Route path="deviation" element={<DeviationPage />} />
            <Route path="change" element={<ChangePage />} />
            <Route path="audit" element={<AuditPage />} />
            <Route path="sae" element={<SaePage />} />
            <Route path="kb" element={<KbPage />} />
            <Route path="sys" element={<SystemPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
