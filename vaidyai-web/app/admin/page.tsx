import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { KpiGrid } from "@/components/dashboard/kpi-grid";
import { TrendsChart } from "@/components/dashboard/trends-chart";
import { AppointmentPanel } from "@/components/dashboard/appointment-panel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { appointments, billingItems, chartSeries, chatLogs, patients } from "@/lib/data";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DoctorsManager } from "@/components/dashboard/doctors-manager";
import { AdminLivePanel } from "@/components/dashboard/admin-live-panel";

type AdminPageProps = {
  searchParams?: Promise<{ tab?: string }>;
};

function DashboardHome() {
  return (
    <>
      <KpiGrid />
      <section className="grid gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2"><TrendsChart /></div>
        <Card>
          <CardHeader><CardTitle>Live Queue</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm text-slate-300">
            <p className="glass p-3">Riya M. waiting for consultation - 3 min</p>
            <p className="glass p-3">Arjun P. waiting for reports - 6 min</p>
            <p className="glass p-3">Nina G. waiting for follow-up - 9 min</p>
          </CardContent>
        </Card>
      </section>
      <section className="grid gap-6 xl:grid-cols-2">
        <AppointmentPanel />
        <Card>
          <CardHeader><CardTitle>AI Alerts</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm text-slate-300">
            <p className="glass p-3">Medication adherence risk flagged for PAT-214.</p>
            <p className="glass p-3">High inbound volume expected between 5-7 PM.</p>
            <p className="glass p-3">2 pending cancellations need verification.</p>
          </CardContent>
        </Card>
      </section>
    </>
  );
}

function AppointmentsView() {
  return (
    <AdminLivePanel />
  );
}

function PatientsView() {
  return (
    <AdminLivePanel />
  );
}

function DoctorsView() {
  return <DoctorsManager />;
}

function ChatLogsView() {
  return (
    <Card>
      <CardHeader><CardTitle>AI Chat Logs</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {chatLogs.length === 0 ? (
          <div className="glass p-4 text-sm text-slate-300">No AI chat logs yet.</div>
        ) : chatLogs.map((log) => (
          <div key={log.id} className="glass p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="font-medium">{log.patient}</p>
              <p className="text-xs text-slate-400">{log.timestamp}</p>
            </div>
            <p className="text-sm text-slate-300">{log.id} - {log.topic}</p>
            <p className="text-sm text-slate-400">Sentiment: {log.sentiment}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function AnalyticsView() {
  return (
    <section className="grid gap-6 xl:grid-cols-3">
      <div className="xl:col-span-2"><TrendsChart /></div>
      <Card>
        <CardHeader><CardTitle>AI Insights</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm text-slate-300">
          <p className="glass p-3">Peak bookings: 10 AM - 12 PM (weekdays).</p>
          <p className="glass p-3">Most requested specialty: General Dentistry.</p>
          <p className="glass p-3">Cancellation risk highest within 2 hours of slot.</p>
        </CardContent>
      </Card>
      <Card className="xl:col-span-3">
        <CardHeader><CardTitle>Weekly Activity</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          {chartSeries.length === 0 ? (
            <div className="glass p-4 text-sm text-slate-300 md:col-span-4">No analytics data available yet.</div>
          ) : chartSeries.map((row) => (
            <div key={row.week} className="glass p-3 text-sm">
              <p className="font-medium">{row.week}</p>
              <p className="text-slate-300">Appointments: {row.appointments}</p>
              <p className="text-slate-300">Patients: {row.patients}</p>
              <p className="text-slate-300">AI Chats: {row.ai}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}

function BillingView() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Billing</CardTitle>
        <Button size="sm">Download Invoices</Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {billingItems.length === 0 ? (
          <div className="glass p-4 text-sm text-slate-300">No billing records yet.</div>
        ) : billingItems.map((item) => (
          <div key={item.id} className="glass p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="font-medium">{item.id}</p>
              <Badge tone={item.status === "paid" ? "confirmed" : "pending"}>{item.status}</Badge>
            </div>
            <p className="text-sm text-slate-300">{item.account} - {item.plan}</p>
            <p className="text-sm text-slate-400">Amount: {item.amount} · Due: {item.due}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function SettingsView() {
  return (
    <Card>
      <CardHeader><CardTitle>Settings</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm text-slate-300">
        <div className="glass p-3">Role permissions: Admin, Doctor, Receptionist</div>
        <div className="glass p-3">Notification channels: Email, SMS, WhatsApp</div>
        <div className="glass p-3">Session policy: 30 minutes inactivity timeout</div>
        <div className="glass p-3">Audit logging: Enabled</div>
      </CardContent>
    </Card>
  );
}

export default async function AdminPage({ searchParams }: AdminPageProps) {
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const tab = resolvedSearchParams?.tab ?? "dashboard";

  const content = (() => {
    if (tab === "appointments") return <AppointmentsView />;
    if (tab === "patients") return <PatientsView />;
    if (tab === "doctors") return <DoctorsView />;
    if (tab === "logs") return <ChatLogsView />;
    if (tab === "analytics") return <AnalyticsView />;
    if (tab === "billing") return <BillingView />;
    if (tab === "settings") return <SettingsView />;
    return <DashboardHome />;
  })();

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex-1">
        <Topbar />
        <main className="space-y-6 p-4 lg:p-8">{content}</main>
      </div>
    </div>
  );
}
