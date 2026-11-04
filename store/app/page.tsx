import { api, inr } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const { items } = await api.products().catch(() => ({ items: [] }));
  const featured = items.slice(0, 3);
  return (
    <div className="fade-in">
      <section className="grid grid-cols-12 gap-4 py-10 md:py-16">
        <div className="col-span-12 md:col-span-5 flex flex-col justify-end order-2 md:order-1">
          <p className="text-sm uppercase tracking-widest text-oxblood">Autumn drop — 6 pieces</p>
          <h1 className="font-display text-5xl md:text-6xl leading-none mt-3">
            Clothes for leaving town.
          </h1>
          <p className="mt-4 max-w-md">
            Heavy cotton, real denim, nothing shiny. Cash on delivery, and our AI
            assistant confirms every order on WhatsApp before it ships.
          </p>
          <p className="mt-6">
            <a href="/shop" className="btn btn-solid">
              Shop the drop
            </a>
          </p>
        </div>
        <div className="col-span-12 md:col-span-7 order-1 md:order-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/products/rack.jpg"
            alt="The ESCAPE autumn rail"
            className="w-full aspect-[4/3] object-cover border rule"
          />
        </div>
      </section>

      <section className="border-t rule py-10">
        <div className="grid grid-cols-12 gap-4 items-baseline mb-6">
          <h2 className="col-span-8 font-display text-3xl">Three to start with</h2>
          <a href="/shop" className="col-span-4 text-right text-sm uppercase tracking-widest">
            All six →
          </a>
        </div>
        <div className="grid grid-cols-12 gap-4">
          {featured.map((p) => (
            <a key={p.slug} href={`/product/${p.slug}`} className="col-span-12 md:col-span-4">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/products/${p.image}`}
                alt={p.name}
                className="w-full aspect-[3/4] object-cover border rule"
              />
              <div className="flex justify-between mt-2">
                <span className="font-medium">{p.name}</span>
                <span>{inr(p.price_paise)}</span>
              </div>
            </a>
          ))}
        </div>
      </section>

      <section className="border-t rule py-10 grid grid-cols-12 gap-4">
        <h2 className="col-span-12 font-display text-3xl mb-2">How ordering works</h2>
        <div className="col-span-12 md:col-span-4 border-t rule pt-3">
          <p className="font-display text-xl">1. Pick your size</p>
          <p className="mt-1 text-sm opacity-80">Chest measured flat, doubled. Between sizes, size up.</p>
        </div>
        <div className="col-span-12 md:col-span-4 border-t rule pt-3">
          <p className="font-display text-xl">2. Confirm on WhatsApp</p>
          <p className="mt-1 text-sm opacity-80">Tap Confirm, or our AI calls you to check items and address.</p>
        </div>
        <div className="col-span-12 md:col-span-4 border-t rule pt-3">
          <p className="font-display text-xl">3. Pay at the door</p>
          <p className="mt-1 text-sm opacity-80">Cash on delivery only. No cards, no advance.</p>
        </div>
      </section>
    </div>
  );
}
