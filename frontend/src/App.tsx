import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { CurveViewerPage } from "./pages/CurveViewer/CurveViewerPage";
import { RiskDashboardPage } from "./pages/RiskDashboard/RiskDashboardPage";
import { TradeBlotterPage } from "./pages/TradeBlotter/TradeBlotterPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<TradeBlotterPage />} />
        <Route path="curve" element={<CurveViewerPage />} />
        <Route path="risk" element={<RiskDashboardPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
