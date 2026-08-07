import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "./components/auth/ProtectedRoute";
import { AppShell } from "./components/layout/AppShell";
import { CurveViewerPage } from "./pages/CurveViewer/CurveViewerPage";
import { LoginPage } from "./pages/Login/LoginPage";
import { PendingApprovalsPage } from "./pages/PendingApprovals/PendingApprovalsPage";
import { RiskDashboardPage } from "./pages/RiskDashboard/RiskDashboardPage";
import { TradeBlotterPage } from "./pages/TradeBlotter/TradeBlotterPage";

export function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<TradeBlotterPage />} />
          <Route path="curve" element={<CurveViewerPage />} />
          <Route path="risk" element={<RiskDashboardPage />} />
          <Route path="approvals" element={<PendingApprovalsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
