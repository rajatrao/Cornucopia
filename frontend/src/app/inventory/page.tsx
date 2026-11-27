import { InventoryView } from "@/components/inventory-view";

export const metadata = { title: "Inventory · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-stone-900">Inventory</h1>
      <InventoryView />
    </main>
  );
}
