"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

type Appointment = {
  id: number;
  patient_id: number | null;
  date: string | null;
  time: string | null;
  reason: string | null;
  is_confirmed: boolean;
};

type Patient = {
  id: number;
  name: string | null;
  phone_number: string | null;
  email: string | null;
};

async function getToken() {
  const body = new URLSearchParams();
  body.append("username", "admin");
  body.append("password", "password");

  const res = await fetch(`${BACKEND_URL}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString()
  });
  if (!res.ok) throw new Error("Failed auth");
  const data = await res.json();
  return data.access_token as string;
}

export function AdminLivePanel() {
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [status, setStatus] = useState("Loading...");

  const load = async () => {
    try {
      setStatus("Refreshing...");
      const token = await getToken();
      const headers = { Authorization: `Bearer ${token}` };

      const [aRes, pRes] = await Promise.all([
        fetch(`${BACKEND_URL}/appointments`, { headers, cache: "no-store" }),
        fetch(`${BACKEND_URL}/patients`, { headers, cache: "no-store" })
      ]);

      if (!aRes.ok || !pRes.ok) throw new Error("Failed to fetch backend data");
      setAppointments(await aRes.json());
      setPatients(await pRes.json());
      setStatus(`Updated at ${new Date().toLocaleTimeString()}`);
    } catch {
      setStatus(`Cannot connect backend at ${BACKEND_URL}`);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <section className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Live Appointments (Backend)</CardTitle>
          <button className="rounded-xl border border-white/15 bg-white/5 px-3 py-1 text-sm" onClick={load}>Refresh</button>
        </CardHeader>
        <CardContent className="space-y-3">
          {appointments.length === 0 ? (
            <div className="glass p-3 text-sm text-slate-300">No appointments found.</div>
          ) : (
            appointments.map((a) => (
              <div key={a.id} className="glass p-3 text-sm">
                <p className="font-medium">Appointment #{a.id}</p>
                <p className="text-slate-300">Patient ID: {a.patient_id ?? "-"}</p>
                <p className="text-slate-300">{a.date ?? "-"} · {a.time ?? "-"}</p>
                <p className="text-slate-300">{a.reason ?? "-"}</p>
                <p className="text-slate-400">Status: {a.is_confirmed ? "confirmed" : "cancelled"}</p>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Live Patients (Backend)</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {patients.length === 0 ? (
            <div className="glass p-3 text-sm text-slate-300">No patients found.</div>
          ) : (
            patients.map((p) => (
              <div key={p.id} className="glass p-3 text-sm">
                <p className="font-medium">{p.name ?? "Unnamed"}</p>
                <p className="text-slate-300">ID: {p.id}</p>
                <p className="text-slate-300">Phone: {p.phone_number ?? "-"}</p>
                <p className="text-slate-400">Email: {p.email ?? "-"}</p>
              </div>
            ))
          )}
          <p className="text-xs text-slate-400">{status}</p>
        </CardContent>
      </Card>
    </section>
  );
}
