import type { Metadata } from "next";
import { Newsreader, Familjen_Grotesk } from "next/font/google";
import "./globals.css";

const serif = Newsreader({ subsets: ["latin"], display: "swap" });
const sans = Familjen_Grotesk({ subsets: ["latin"], display: "swap" });

export const metadata: Metadata = { title: "Agent dashboard" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.className} ${sans.className}`}>
      <body>{children}</body>
    </html>
  );
}
