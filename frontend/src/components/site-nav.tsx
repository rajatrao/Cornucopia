"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { OperatorMenu } from "@/components/operator-menu";

const GROUPS: { title: string; links: { href: string; label: string; icon: string }[] }[] = [
  {
    title: "Operate",
    links: [
      { href: "/", label: "Command Center", icon: "◎" },
      { href: "/recompilation", label: "Recompilation", icon: "⟲" },
      { href: "/approvals", label: "Approvals", icon: "✓" },
      { href: "/events", label: "Events", icon: "⚡" },
    ],
  },
  {
    title: "Resources",
    links: [
      { href: "/resources", label: "Resources", icon: "▤" },
      { href: "/inventory", label: "Inventory", icon: "▦" },
    ],
  },
  {
    title: "Analyze",
    links: [
      { href: "/simulation", label: "Simulation", icon: "◇" },
      { href: "/optimizer", label: "Optimizer", icon: "∑" },
      { href: "/compiler", label: "Compiler", icon: "⌘" },
    ],
  },
  {
    title: "Observe",
    links: [
      { href: "/executions", label: "Agent", icon: "◉" },
      { href: "/history", label: "Audit", icon: "☰" },
    ],
  },
];

export function SiteNav() {
  const path = usePathname();
  if (path === "/login") return null;
  return (
    <aside className="z-10 flex w-full flex-col bg-slate-950 text-slate-300 lg:fixed lg:inset-y-0 lg:left-0 lg:w-60">
      <div className="flex items-center justify-between gap-2 px-5 py-4 lg:block">
        <Link href="/" className="block">
          <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-emerald-300 bg-clip-text text-lg font-extrabold tracking-tight text-transparent">CORNUCOPIA</span>
          <span className="hidden text-[11px] text-slate-500 lg:block">When resources change, the feast goes on.</span>
        </Link>
        <div className="lg:hidden">
          <OperatorMenu />
        </div>
      </div>
      <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-1 lg:flex-col lg:gap-4 lg:overflow-y-auto lg:pb-0">
        {GROUPS.map((g) => (
          <div key={g.title} className="flex gap-1 lg:flex-col">
            <p className="hidden px-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500 lg:block">{g.title}</p>
            {g.links.map((l) => {
              const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={active ? "page" : undefined}
                  className={`flex shrink-0 items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm transition ${
                    active ? "bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-lg shadow-violet-900/40" : "text-slate-300 hover:bg-slate-800 hover:text-white"
                  }`}
                >
                  <span aria-hidden className="w-4 text-center text-xs opacity-80">
                    {l.icon}
                  </span>
                  {l.label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="hidden border-t border-slate-800 px-5 py-4 lg:block">
        <OperatorMenu />
      </div>
    </aside>
  );
}
