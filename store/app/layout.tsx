import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ESCAPE — clothes for leaving town",
  description: "Heavy cotton tees, hoodies and denim. Cash on delivery.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Familjen+Grotesk:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <header className="border-b rule">
          <div className="mx-auto max-w-6xl px-4 py-4 grid grid-cols-12 gap-4 items-baseline">
            <a href="/" className="col-span-6 font-display text-2xl tracking-tight">
              ESCAPE
            </a>
            <nav className="col-span-6 flex justify-end gap-6 text-sm uppercase tracking-widest">
              <a href="/shop">Shop</a>
              <a href="/cart">Cart</a>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4">{children}</main>
        <footer className="border-t rule mt-20">
          <div className="mx-auto max-w-6xl px-4 py-8 grid grid-cols-12 gap-4 text-sm">
            <p className="col-span-12 md:col-span-6">
              Cash on delivery. Confirm every order on WhatsApp before we ship.
            </p>
            <p className="col-span-12 md:col-span-6 md:text-right opacity-70">
              Photos: Unsplash free-license library. Try-on previews are generated and deleted
              within an hour.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
