import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/session";
import { AppShell } from "./components/AppShell";
import { EmptyState, Loading } from "./components/ui";
import { canSeeGrowth, canSeeInsights, homePath, isStaff } from "./lib/roles";
import { LoginPage } from "./pages/LoginPage";

/** Route-level code splitting (S12.4): a page's code (and heavy libraries like the charts)
 * loads when its route opens. The pages export named components, hence the `default` mapping. */
const BrandSignalsPage = lazy(() => import("./pages/BrandSignalsPage").then((m) => ({ default: m.BrandSignalsPage })));
const GrowthPage = lazy(() => import("./pages/GrowthPage").then((m) => ({ default: m.GrowthPage })));
const GrowthCalendarPage = lazy(() => import("./pages/GrowthCalendarPage").then((m) => ({ default: m.GrowthCalendarPage })));
const DashboardPage = lazy(() => import("./pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const SegmentsPage = lazy(() => import("./pages/SegmentsPage").then((m) => ({ default: m.SegmentsPage })));
const InsightsPage = lazy(() => import("./pages/InsightsPage").then((m) => ({ default: m.InsightsPage })));
const ApprovalDetailPage = lazy(() => import("./pages/ApprovalDetailPage").then((m) => ({ default: m.ApprovalDetailPage })));
const ApprovalsPage = lazy(() => import("./pages/ApprovalsPage").then((m) => ({ default: m.ApprovalsPage })));
const CasePage = lazy(() => import("./pages/CasePage").then((m) => ({ default: m.CasePage })));
const CasesPage = lazy(() => import("./pages/CasesPage").then((m) => ({ default: m.CasesPage })));
const DevPage = lazy(() => import("./pages/DevPage").then((m) => ({ default: m.DevPage })));
const HelpPage = lazy(() => import("./pages/HelpPage").then((m) => ({ default: m.HelpPage })));
const QueuePage = lazy(() => import("./pages/QueuePage").then((m) => ({ default: m.QueuePage })));
const OrderDetailPage = lazy(() => import("./pages/OrderDetailPage").then((m) => ({ default: m.OrderDetailPage })));
const OrdersPage = lazy(() => import("./pages/OrdersPage").then((m) => ({ default: m.OrdersPage })));
const PoliciesPage = lazy(() => import("./pages/PoliciesPage").then((m) => ({ default: m.PoliciesPage })));
const PrivacyPage = lazy(() => import("./pages/PrivacyPage").then((m) => ({ default: m.PrivacyPage })));
const PrivacyRequestsPage = lazy(() => import("./pages/PrivacyRequestsPage").then((m) => ({ default: m.PrivacyRequestsPage })));
const ReadableExportPage = lazy(() => import("./pages/ReadableExportPage").then((m) => ({ default: m.ReadableExportPage })));
const ReportProblemPage = lazy(() => import("./pages/ReportProblemPage").then((m) => ({ default: m.ReportProblemPage })));
const PlatformApp = lazy(() => import("./platform/PlatformApp").then((m) => ({ default: m.PlatformApp })));

/** Hides screens a role has no use for. Access itself is enforced by the API on every call. */
function Only({ when, children }: { when: boolean; children: ReactNode }) {
  return when ? <>{children}</> : <NotFound />;
}

function NotFound() {
  return <EmptyState title="Page not found">The page you're looking for doesn't exist or isn't available to you.</EmptyState>;
}

/** The platform portal is its own area with its own sign-in: it never waits for, or shares, a
 * business session. */
export function App() {
  const { pathname } = useLocation();
  if (pathname === "/platform" || pathname.startsWith("/platform/")) {
    return (
      <Suspense fallback={<Loading />}>
        <PlatformApp />
      </Suspense>
    );
  }
  return <TenantApp />;
}

function TenantApp() {
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
        <Route path="/dashboard" element={<Only when={staff}><DashboardPage /></Only>} />
        <Route path="/segments" element={<Only when={staff}><SegmentsPage /></Only>} />
        <Route path="/growth/calendar" element={<Only when={canSeeGrowth(me.role, me.growth_enabled)}><GrowthCalendarPage /></Only>} />
        <Route path="/growth" element={<Only when={canSeeGrowth(me.role, me.growth_enabled)}><GrowthPage /></Only>} />
        <Route path="/growth/brands" element={<Only when={me.role === "hq_owner" && canSeeGrowth(me.role, me.growth_enabled)}><BrandSignalsPage /></Only>} />
        <Route path="/dev" element={<Navigate to="/demo" replace />} />
        <Route path="/demo" element={<Only when={me.role === "hq_owner"}><DevPage /></Only>} />
        <Route path="/policies" element={<PoliciesPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
