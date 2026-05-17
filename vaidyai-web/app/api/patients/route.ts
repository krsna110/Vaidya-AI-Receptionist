import { NextResponse } from "next/server";
import { patients } from "@/lib/data";

export async function GET() {
  return NextResponse.json(patients);
}
