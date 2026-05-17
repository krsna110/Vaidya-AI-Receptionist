import { NextResponse } from "next/server";

type Doctor = {
  id: string;
  name: string;
  specialty: string;
  availability: string;
  rating: number;
};

const doctorStore: Doctor[] = [];

export async function GET() {
  return NextResponse.json(doctorStore);
}

export async function POST(req: Request) {
  const body = await req.json();
  const name = (body?.name ?? "").toString().trim();
  const specialty = (body?.specialty ?? "").toString().trim();
  const availability = (body?.availability ?? "").toString().trim();
  const ratingRaw = Number(body?.rating ?? 0);

  if (!name || !specialty || !availability) {
    return NextResponse.json({ error: "name, specialty, availability are required" }, { status: 400 });
  }

  const rating = Number.isFinite(ratingRaw) ? Math.max(0, Math.min(5, ratingRaw)) : 0;

  const doctor: Doctor = {
    id: `DOC-${Date.now()}`,
    name,
    specialty,
    availability,
    rating
  };

  doctorStore.push(doctor);
  return NextResponse.json(doctor, { status: 201 });
}
