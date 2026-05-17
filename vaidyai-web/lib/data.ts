export type Appointment = {
  id: string;
  patientName: string;
  doctor: string;
  date: string;
  time: string;
  status: "confirmed" | "pending" | "cancelled";
  reason: string;
  channel: "AI Chat" | "Phone" | "Walk-in";
};

export type Patient = {
  id: string;
  name: string;
  age: number;
  phone: string;
  condition: string;
  risk: "low" | "medium" | "high";
  summary: string;
};

export const kpis = [
  { label: "Total Patients", value: "0", delta: "0%" },
  { label: "Appointments Today", value: "0", delta: "0%" },
  { label: "AI Conversations", value: "0", delta: "0%" },
  { label: "Revenue", value: "$0", delta: "0%" },
  { label: "Pending Cases", value: "0", delta: "0%" }
];

export const appointments: Appointment[] = [];

export const patients: Patient[] = [];

export const chartSeries: Array<{ week: string; appointments: number; patients: number; ai: number }> = [];

export const quickPrompts = [
  "Book a dermatologist visit",
  "Check my upcoming appointments",
  "I have fever for 2 days",
  "Reschedule my consultation"
];

export const doctors: Array<{ id: string; name: string; specialty: string; availability: string; rating: number }> = [];

export const chatLogs: Array<{ id: string; patient: string; topic: string; sentiment: string; timestamp: string }> = [];

export const billingItems: Array<{ id: string; account: string; plan: string; amount: string; status: "paid" | "pending"; due: string }> = [];
