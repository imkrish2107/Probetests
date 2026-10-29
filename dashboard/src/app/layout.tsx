import type { Metadata } from "next";
import { Red_Hat_Display } from "next/font/google";
import "./globals.css";

const font = Red_Hat_Display({ subsets: ["latin"], weight: ["400", "500", "700"] });

export const metadata: Metadata = { title: "Your Cafe dashboard" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={font.className}>{children}</body>
    </html>
  );
}
