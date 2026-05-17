"use client";

import { Bell, CircleDot, Search } from "lucide-react";
import { Input } from "@/components/ui/input";

export function Topbar() {
  return (
    <header className="sticky top-0 z-40 flex items-center justify-between gap-4 border-b border-white/10 bg-slate-950/70 px-4 py-3 backdrop-blur-xl lg:px-8">
      <div className="relative w-full max-w-xl">
        <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
        <Input className="pl-9" placeholder="Search patients, appointments, doctors..." />
      </div>
      <div className="flex items-center gap-4">
        <div className="hidden items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-cyan-200 sm:flex">
          <CircleDot className="h-3 w-3 fill-cyan-300 text-cyan-300" />
          System healthy
        </div>
        <button className="rounded-2xl border border-white/15 bg-white/5 p-2"><Bell className="h-4 w-4" /></button>
        <div className="rounded-2xl border border-white/15 bg-white/5 px-3 py-2 text-sm">Admin</div>
      </div>
    </header>
  );
}
