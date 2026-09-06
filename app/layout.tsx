import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "PrimeHub Bot — Salaar", description: "Phase 1 customer chat shell and admin inbox" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
