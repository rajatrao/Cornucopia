import { ApprovalCenter } from "@/components/approval-center";

export const metadata = { title: "Approval Center · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-stone-900">Approval Center</h1>
      <p className="text-sm text-stone-600">
        A plan being feasible never authorises it. Each proposal is bound to its plan version, fingerprint and the operational state it was computed against; the database re-checks all of them when it commits.
      </p>
      <ApprovalCenter />
    </main>
  );
}
