import Link from "next/link";

import { OperatorMenu } from "@/components/operator-menu";

const LINKS = [
  { href: "/", label: "Command Center" },
  { href: "/recompilation", label: "Recompilation" },
  { href: "/approvals", label: "Approvals" },
  { href: "/events", label: "Events" },
  { href: "/resources", label: "Resources" },
  { href: "/inventory", label: "Inventory" },
  { href: "/simulation", label: "Simulation" },
  { href: "/executions", label: "Agent" },
  { href: "/optimizer", label: "Optimizer" },
  { href: "/compiler", label: "Compiler" },
  { href: "/history", label: "Audit" },
];

export function SiteNav() {
  return (
    <header className="border-b border-amber-900/20 bg-amber-50/90">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center justify-between gap-4">
          <Link href="/" className="font-bold tracking-tight text-stone-900">
            CORNUCOPIA
          </Link>
          <OperatorMenu />
        </div>
        <nav aria-label="Main" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="text-stone-700 hover:text-amber-900 hover:underline">
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
