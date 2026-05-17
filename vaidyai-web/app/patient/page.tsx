import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function PatientPage() {
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 lg:px-8">
      <Card className="p-6">
        <h1 className="text-2xl font-semibold">Welcome back, Krishna</h1>
        <p className="text-sm text-slate-300">Your AI health concierge is active.</p>
      </Card>
      <section className="grid gap-6 lg:grid-cols-3">
        <Card><CardHeader><CardTitle>Upcoming Appointments</CardTitle></CardHeader><CardContent className="text-sm text-slate-300">May 18, 11:00 AM Â· Dr. Mehta</CardContent></Card>
        <Card><CardHeader><CardTitle>Medical Records</CardTitle></CardHeader><CardContent className="text-sm text-slate-300">4 recent reports available.</CardContent></Card>
        <Card><CardHeader><CardTitle>Health Insights</CardTitle></CardHeader><CardContent className="text-sm text-slate-300">Hydration consistency improved by 12%.</CardContent></Card>
      </section>
      <Card>
        <CardHeader><CardTitle>Book Appointment</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm text-slate-300">
          <p className="glass p-3">Step 1: Choose specialty</p>
          <p className="glass p-3">Step 2: Pick calendar date & slot</p>
          <p className="glass p-3">Step 3: Confirm details</p>
          <Button>Start Booking Wizard</Button>
        </CardContent>
      </Card>
    </main>
  );
}
