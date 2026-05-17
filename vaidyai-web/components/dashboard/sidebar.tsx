"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Bot, CalendarClock, CreditCard, LayoutDashboard, Settings, Stethoscope, Users } from "lucide-react";
import { cn } from "@/lib/utils";

const items = [
  { href: "/admin", label: "Dashboard", icon: LayoutDashboard },
  { href: "/admin?tab=appointments", label: "Appointments", icon: CalendarClock },
  { href: "/admin?tab=patients", label: "Patients", icon: Users },
  { href: "/admin?tab=doctors", label: "Doctors", icon: Stethoscope },
  { href: "/admin?tab=logs", label: "AI Chat Logs", icon: Bot },
  { href: "/admin?tab=analytics", label: "Analytics", icon: Activity },
  { href: "/admin?tab=billing", label: "Billing", icon: CreditCard },
  { href: "/admin?tab=settings", label: "Settings", icon: Settings }
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-screen w-72 flex-col border-r border-white/10 bg-slate-950/50 p-5 backdrop-blur-xl lg:flex">
      <div className="mb-8 flex items-center gap-3">
        <div className="h-10 w-10 rounded-2xl bg-gradient-to-br from-cyan-300 to-blue-400" />
        <div>
          <p className="font-semibold">Vaidya AI</p>
          <p className="text-xs text-slate-400">Medical Intelligence</p>
        </div>
      </div>
      <nav className="space-y-1">
        {items.map((item) => {
          const Icon = item.icon;
          const active = pathname === "/admin" && item.href === "/admin";
          return (
            <Link key={item.label} href={item.href as any} className={cn("flex items-center gap-3 rounded-2xl px-4 py-2 text-sm text-slate-300 transition hover:bg-white/10", active && "bg-cyan/20 text-white")}>
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
