import Link from "next/link";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/resources", label: "Resources" },
  { href: "/inventory", label: "Inventory" },
  { href: "/events", label: "Event Center" },
  { href: "/compiler", label: "Compiler" },
  { href: "/optimizer", label: "Optimizer" },
  { href: "/executions", label: "Agent" },
  { href: "/history", label: "Audit history" },
];

export function SiteNav() {
  return (
    <header className="border-b border-amber-900/20 bg-amber-50/90">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
        <Link href="/" className="font-bold tracking-tight text-stone-900">
          CORNUCOPIA
        </Link>
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
