"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

type Doctor = {
  id: string;
  name: string;
  specialty: string;
  availability: string;
  rating: number;
};

const initialForm = {
  name: "",
  specialty: "",
  availability: "",
  rating: "4.5"
};

export function DoctorsManager() {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [form, setForm] = useState(initialForm);
  const [status, setStatus] = useState("Ready");

  const loadDoctors = async () => {
    const res = await fetch("/api/doctors", { cache: "no-store" });
    const data = await res.json();
    setDoctors(Array.isArray(data) ? data : []);
  };

  useEffect(() => {
    loadDoctors().catch(() => setStatus("Failed to load doctors"));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("Registering doctor...");

    const res = await fetch("/api/doctors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.name,
        specialty: form.specialty,
        availability: form.availability,
        rating: Number(form.rating)
      })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setStatus(err?.error ?? "Failed to register doctor");
      return;
    }

    setForm(initialForm);
    await loadDoctors();
    setStatus("Doctor registered successfully.");
  };

  return (
    <section className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Register Doctor</CardTitle></CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={submit}>
            <Input
              placeholder="Doctor name"
              value={form.name}
              onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
            />
            <Input
              placeholder="Specialty (e.g., Cardiology)"
              value={form.specialty}
              onChange={(e) => setForm((prev) => ({ ...prev, specialty: e.target.value }))}
            />
            <Input
              placeholder="Availability (e.g., 10:00 AM - 4:00 PM)"
              value={form.availability}
              onChange={(e) => setForm((prev) => ({ ...prev, availability: e.target.value }))}
            />
            <Input
              placeholder="Rating (0 to 5)"
              value={form.rating}
              onChange={(e) => setForm((prev) => ({ ...prev, rating: e.target.value }))}
            />
            <div className="flex gap-2">
              <Button type="submit">Register</Button>
              <Button type="button" variant="outline" onClick={() => setForm(initialForm)}>Reset</Button>
            </div>
            <p className="text-xs text-slate-400">{status}</p>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Doctor Directory</CardTitle>
          <Button variant="outline" size="sm" onClick={() => loadDoctors()}>Refresh</Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {doctors.length === 0 ? (
            <div className="glass p-4 text-sm text-slate-300">No doctors registered yet.</div>
          ) : (
            doctors.map((doc) => (
              <div key={doc.id} className="glass p-4">
                <div className="mb-1 flex items-center justify-between">
                  <p className="font-medium">{doc.name}</p>
                  <p className="text-sm text-cyan-200">{doc.rating.toFixed(1)} / 5.0</p>
                </div>
                <p className="text-sm text-slate-300">{doc.specialty}</p>
                <p className="text-sm text-slate-400">{doc.availability}</p>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </section>
  );
}
