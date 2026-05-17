import { kpis } from "@/lib/data";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function KpiGrid() {
  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      {kpis.map((item) => (
        <Card key={item.label} className="bg-white/[0.04]">
          <CardHeader>
            <CardTitle className="text-sm text-slate-300">{item.label}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold">{item.value}</p>
            <p className="text-xs text-cyan-200">{item.delta} this month</p>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}
