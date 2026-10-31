import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/session";
import { AppShell } from "./components/AppShell";
import { EmptyState, Loading } from "./components/ui";
import { canSeeGrowth, canSeeInsights, homePath, isStaff } from "./lib/roles";
import { GrowthPage } from "./pages/GrowthPage";
import { InsightsPage } from "./pages/InsightsPage";
import { ApprovalDetailPage } from "./pages/ApprovalDetailPage";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { CasePage } from "./pages/CasePage";
import { CasesPage } from "./pages/CasesPage";
import { DevPage } from "./pages/DevPage";
import { HelpPage } from "./pages/HelpPage";
import { QueuePage } from "./pages/QueuePage";
import { LoginPage } from "./pages/LoginPage";
import { OrderDetailPage } from "./pages/OrderDetailPage";
import { OrdersPage } from "./pages/OrdersPage";
import { PoliciesPage } from "./pages/PoliciesPage";
import { PrivacyPage } from "./pages/PrivacyPage";
import { PrivacyRequestsPage } from "./pages/PrivacyRequestsPage";
import { ReadableExportPage } from "./pages/ReadableExportPage";
import { ReportProblemPage } from "./pages/ReportProblemPage";

/** Hides screens a role has no use for. Access itself is enforced by the API on every call. */
function Only({ when, children }: { when: boolean; children: ReactNode }) {
  return when ? <>{children}</> : <NotFound />;
}

function NotFound() {
  return <EmptyState title="Page not found">The page you're looking for doesn't exist or isn't available to you.</EmptyState>;
}

export function App() {
  const { status, me, signedOutByUser } = useAuth();
  const location = useLocation();

  if (status === "loading") return <Loading label="Signing you in…" />;

  if (status === "signed_out" || !me) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* Come back to a deep link or an expired session's page; not to the page someone left
            when they signed out. */}
        <Route path="*" element={<Navigate to="/login" replace state={signedOutByUser ? null : { from: location.pathname }} />} />
      </Routes>
    );
  }

  const customer = me.role === "customer";
  const staff = isStaff(me.role);
  const from = (location.state as { from?: string } | null)?.from;

  return (
    <Routes>
      <Route path="/login" element={<Navigate to={from && from !== "/login" ? from : homePath(me.role)} replace />} />
      <Route element={<AppShell />}>
        <Route index element={<Navigate to={homePath(me.role)} replace />} />
        <Route path="/orders" element={<Only when={customer}><OrdersPage /></Only>} />
        <Route path="/orders/:orderId" element={<Only when={customer}><OrderDetailPage /></Only>} />
        <Route path="/orders/:orderId/report" element={<Only when={customer}><ReportProblemPage /></Only>} />
        <Route path="/privacy" element={<Only when={customer}><PrivacyPage /></Only>} />
        <Route path="/privacy/export" element={<Only when={customer}><ReadableExportPage /></Only>} />
        <Route path="/privacy-requests" element={<Only when={me.role === "hq_owner"}><PrivacyRequestsPage /></Only>} />
        <Route path="/queue" element={<Only when={staff}><QueuePage /></Only>} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/cases/:caseId" element={<CasePage />} />
        <Route path="/approvals" element={<Only when={staff}><ApprovalsPage /></Only>} />
        <Route path="/approvals/:proposalId" element={<Only when={staff}><ApprovalDetailPage /></Only>} />
        <Route path="/insights" element={<Only when={canSeeInsights(me.role)}><InsightsPage /></Only>} />
        <Route path="/growth" element={<Only when={canSeeGrowth(me.role, me.growth_enabled)}><GrowthPage /></Only>} />
        <Route path="/dev" element={<Navigate to="/demo" replace />} />
        <Route path="/demo" element={<Only when={me.role === "hq_owner"}><DevPage /></Only>} />
        <Route path="/policies" element={<PoliciesPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
