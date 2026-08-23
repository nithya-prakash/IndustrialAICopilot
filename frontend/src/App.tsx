import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute, RequireRole } from "./components/ProtectedRoute";
import { AuthProvider } from "./context/AuthContext";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { AuditLogPage } from "./pages/AuditLogPage";
import { CopilotPage } from "./pages/CopilotPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DiagnosisDetailPage } from "./pages/DiagnosisDetailPage";
import { KnowledgeBasePage } from "./pages/KnowledgeBasePage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/knowledge-base" element={<KnowledgeBasePage />} />
            <Route path="/copilot" element={<CopilotPage />} />
            <Route path="/diagnoses/:id" element={<DiagnosisDetailPage />} />
            <Route
              path="/approvals"
              element={
                <RequireRole roles={["supervisor", "admin"]}>
                  <ApprovalsPage />
                </RequireRole>
              }
            />
            <Route
              path="/audit-log"
              element={
                <RequireRole roles={["admin"]}>
                  <AuditLogPage />
                </RequireRole>
              }
            />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
