import { api, inr } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Shop() {
  const { items } = await api.products().catch(() => ({ items: [] }));
  if (!items.length)
    return <p className="py-16">Nothing on the rail right now — the backend may be asleep.</p>;
  return (
    <div className="fade-in py-10">
      <h1 className="font-display text-5xl">The autumn drop</h1>
      <p className="mt-2 opacity-80">Six pieces. Heavy fabric, honest stitching.</p>
      <div className="grid grid-cols-12 gap-x-4 gap-y-10 mt-8">
        {items.map((p, i) => (
          <a
            key={p.slug}
            href={`/product/${p.slug}`}
            className={`col-span-6 ${i % 2 ? "md:col-span-4 md:col-start-6" : "md:col-span-4 md:col-start-2"}`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`/products/${p.image}`}
              alt={p.name}
              className="w-full aspect-[3/4] object-cover border rule"
            />
            <div className="flex justify-between mt-2 gap-2">
              <span className="font-medium">{p.name}</span>
              <span className="whitespace-nowrap">{inr(p.price_paise)}</span>
            </div>
            <p className="text-sm opacity-70">{p.fabric}</p>
          </a>
        ))}
      </div>
    </div>
  );
}
