import { cn } from "@/lib/utils";

const map = {
  confirmed: "bg-emerald-300/15 text-emerald-200 border-emerald-300/30",
  pending: "bg-amber-300/15 text-amber-200 border-amber-300/30",
  cancelled: "bg-red-300/15 text-red-200 border-red-300/30",
  low: "bg-cyan-300/15 text-cyan-200 border-cyan-300/30",
  medium: "bg-blue-300/15 text-blue-200 border-blue-300/30",
  high: "bg-red-300/15 text-red-200 border-red-300/30"
} as const;

export function Badge({ tone, children }: { tone: keyof typeof map; children: React.ReactNode }) {
  return <span className={cn("rounded-full border px-2 py-1 text-xs", map[tone])}>{children}</span>;
}
