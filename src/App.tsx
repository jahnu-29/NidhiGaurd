import { useState } from "react";
import LoginPage from "@/pages/LoginPage";
import Layout, { type Page } from "@/components/Layout";
import DashboardPage from "@/pages/DashboardPage";
import ProjectsPage from "@/pages/ProjectsPage";
import ProjectInvestigationPage from "@/pages/ProjectInvestigationPage";
import RiskAnalysisPage from "@/pages/RiskAnalysisPage";
import ContractorsPage from "@/pages/ContractorsPage";
import GeographicPage from "@/pages/GeographicPage";
import InvestigationQueuePage from "@/pages/InvestigationQueuePage";
import ReportsPage from "@/pages/ReportsPage";
import UsersPage from "@/pages/UsersPage";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { canAccessPage, canInvestigate } from "@/auth/permissions";

// Stage 6.6 — the application is only rendered for a signed-in user. Page
// visibility follows the user's role (UX only; the backend enforces access).
export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}

function AppShell() {
  const { status, user, logout } = useAuth();
  const [page, setPage] = useState<Page>("dashboard");
  const [investigatingProject, setInvestigatingProject] = useState<string | null>(null);

  if (status === "checking") {
    return <div style={{ padding: "3rem", textAlign: "center", color: "#4b6c8e", fontSize: "0.85rem" }}>Checking session…</div>;
  }
  if (status !== "authenticated" || !user) {
    return <LoginPage />;
  }

  const role = user.role;
  const allowedPage: Page = canAccessPage(role, page) ? page : "dashboard";
  const mayInvestigate = canInvestigate(role);

  function navigate(p: Page) {
    setPage(p);
    setInvestigatingProject(null);
  }

  function viewProject(id: string) {
    if (!mayInvestigate) return; // Viewer: no project investigation view
    setInvestigatingProject(id);
    setPage("projects");
  }

  async function handleLogout() {
    await logout();
    setPage("dashboard");
    setInvestigatingProject(null);
  }

  return (
    <Layout page={allowedPage} onNavigate={navigate} username={user.username} role={role} onLogout={handleLogout}>
      {allowedPage === "dashboard" && <DashboardPage onViewProject={viewProject} />}
      {allowedPage === "projects" && investigatingProject && mayInvestigate && (
        <ProjectInvestigationPage projectId={investigatingProject} onBack={() => setInvestigatingProject(null)} />
      )}
      {allowedPage === "projects" && !(investigatingProject && mayInvestigate) && <ProjectsPage onViewProject={viewProject} />}
      {allowedPage === "risk-analysis" && <RiskAnalysisPage />}
      {allowedPage === "contractors" && <ContractorsPage />}
      {allowedPage === "geographic" && <GeographicPage />}
      {allowedPage === "investigation-queue" && <InvestigationQueuePage />}
      {allowedPage === "reports" && <ReportsPage />}
      {allowedPage === "users" && <UsersPage currentUserId={user.id} />}
    </Layout>
  );
}