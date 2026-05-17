import { appointments } from "@/lib/data";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function AppointmentPanel() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Appointments</CardTitle>
        <Button variant="outline" size="sm">Filters</Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {appointments.map((item) => (
          <div key={item.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <div className="mb-2 flex items-start justify-between gap-2">
              <div>
                <p className="font-medium">{item.patientName}</p>
                <p className="text-xs text-slate-400">{item.reason} Â· {item.date} Â· {item.time}</p>
              </div>
              <Badge tone={item.status}>{item.status}</Badge>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline">Reschedule</Button>
              <Button size="sm" variant="ghost">Open</Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
