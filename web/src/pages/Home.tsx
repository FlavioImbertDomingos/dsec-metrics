import { ClipboardCheck, Gauge, LayoutDashboard } from "lucide-react";

import type { Me } from "@/api/client";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";

const NEXT = [
  {
    Icon: Gauge,
    title: "Metrics",
    body: "Metric and control definitions, the evaluator and sample data arrive in milestone M1.",
  },
  {
    Icon: LayoutDashboard,
    title: "Dashboards",
    body: "Team operations, management and risk committee dashboards arrive in milestone M2.",
  },
  {
    Icon: ClipboardCheck,
    title: "Audit room",
    body: "Signed evidence packages and the auditor's landing page arrive in milestone M3.",
  },
];

export function Home({ me }: { me: Me }) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome, {me.display_name}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Signed in as <span className="font-medium text-foreground">{me.username}</span>. The
          platform skeleton is running; nothing is measured yet.
        </p>
      </div>
      <ul className="grid gap-4 md:grid-cols-3">
        {NEXT.map(({ Icon, title, body }) => (
          <li key={title}>
            <Card className="h-full">
              <Icon className="size-5 text-muted-foreground" aria-hidden="true" />
              <CardTitle className="mt-3">{title}</CardTitle>
              <CardDescription>{body}</CardDescription>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
