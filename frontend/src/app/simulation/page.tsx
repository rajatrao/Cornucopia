import { SimulationLab } from "@/components/simulation-lab";

export const metadata = { title: "Simulation Laboratory · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-stone-900">Simulation Laboratory</h1>
      <SimulationLab />
    </main>
  );
}
