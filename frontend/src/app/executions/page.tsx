import { ExecutionsView } from "@/components/executions-view";

export const metadata = { title: "Agent executions · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-stone-900">Agent executions</h1>
      <p className="text-sm text-stone-600">
        The recovery agent runs on the Fly.io Sprite, independently of this page. Every node it completes is checkpointed in Supabase.
      </p>
      <ExecutionsView />
    </main>
  );
}
