import { CompilerView } from "@/components/compiler-view";

export const metadata = { title: "Resource Compiler · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-stone-900">Resource Compiler</h1>
      <CompilerView />
    </main>
  );
}
