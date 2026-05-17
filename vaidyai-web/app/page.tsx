import Link from "next/link";
import { ArrowRight, Bot, CalendarCheck2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function LandingPage() {
  return (
    <main className="mx-auto max-w-7xl space-y-20 px-6 py-10 lg:px-10">
      <section className="glass p-8 lg:p-14">
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <div className="space-y-6">
            <p className="inline-flex rounded-full border border-cyan/40 bg-cyan/10 px-3 py-1 text-xs text-cyan-200">AI Healthcare Receptionist Platform</p>
            <h1 className="text-4xl font-semibold leading-tight lg:text-6xl">Vaidya AI powers modern clinics with intelligent reception workflows.</h1>
            <p className="text-slate-300">Premium scheduling, patient intake, and realtime AI concierge in one secure healthcare SaaS platform.</p>
            <div className="flex flex-wrap gap-3">
              <Link href="/admin"><Button>Open Admin <ArrowRight className="ml-2 h-4 w-4" /></Button></Link>
              <Link href="/chat"><Button variant="outline">Try AI Chat</Button></Link>
            </div>
          </div>
          <Card className="p-6">
            <div className="space-y-4">
              <div className="glass p-4">
                <p className="text-sm text-slate-300">Weekly Summary</p>
                <p className="text-2xl font-semibold">+38% faster bookings</p>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {[Bot, CalendarCheck2, ShieldCheck].map((Icon, idx) => (
                  <div key={idx} className="glass p-4"><Icon className="mb-2 h-5 w-5 text-cyan-300" /><p className="text-xs text-slate-300">Enterprise-grade workflow</p></div>
                ))}
              </div>
            </div>
          </Card>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        {["Smart Appointment Automation", "AI Symptom Triage", "Realtime Care Operations"].map((title) => (
          <Card key={title} className="p-6">
            <h3 className="mb-2 text-lg font-semibold">{title}</h3>
            <p className="text-sm text-slate-300">Purpose-built for fast clinical operations with premium UX patterns and scalable architecture.</p>
          </Card>
        ))}
      </section>
    </main>
  );
}
