import { EventCenter } from "@/components/event-center";

export const metadata = { title: "Event Center · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-stone-900">Event Center</h1>
      <EventCenter />
    </main>
  );
}
