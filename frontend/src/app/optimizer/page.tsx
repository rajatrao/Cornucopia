import { OptimizerView } from "@/components/optimizer-view";

export const metadata = { title: "Optimizer · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-stone-900">Recovery Optimizer</h1>
      <OptimizerView />
    </main>
  );
}
