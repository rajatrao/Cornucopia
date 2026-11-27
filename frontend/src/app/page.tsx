import { CommandCenter } from "@/components/command-center";

export const metadata = { title: "Command Center · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <CommandCenter />
    </main>
  );
}
