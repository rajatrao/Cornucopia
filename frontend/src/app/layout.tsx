import type { Metadata } from "next";

import { SiteNav } from "@/components/site-nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "CORNUCOPIA",
  description: "Autonomous resource compiler. When resources change, the feast goes on.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="bg-amber-50 text-stone-900 antialiased">
        <SiteNav />
        {children}
      </body>
    </html>
  );
}
