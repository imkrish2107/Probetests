"use client";

import { useEffect, useState } from "react";
import { api, inr, type Product } from "@/lib/api";
import { addLine } from "@/lib/cart";
import TryOn from "@/components/TryOn";

const SIZES = ["XS", "S", "M", "L", "XL"];

export default function ProductPage({ params }: { params: { slug: string } }) {
  const [p, setP] = useState<Product | null>(null);
  const [tryonOn, setTryonOn] = useState(true);
  const [size, setSize] = useState("M");
  const [added, setAdded] = useState(false);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    api
      .products()
      .then(({ items, tryon }) => {
        const found = items.find((x) => x.slug === params.slug);
        if (found) {
          setP(found);
          setTryonOn(tryon !== false);
        } else setMissing(true);
      })
      .catch(() => setMissing(true));
  }, [params.slug]);

  if (missing) return <p className="py-16">That piece isn’t on the rail.</p>;
  if (!p) return <p className="py-16">Hanging it up…</p>;

  return (
    <div className="fade-in py-10 grid grid-cols-12 gap-6">
      <div className="col-span-12 md:col-span-6">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/products/${p.image}`} alt={p.name} className="w-full border rule" />
      </div>
      <div className="col-span-12 md:col-span-5 md:col-start-8">
        <h1 className="font-display text-4xl">{p.name}</h1>
        <p className="text-xl mt-2">{inr(p.price_paise)}</p>
        <dl className="mt-4 text-sm space-y-1 border-t rule pt-4">
          <div className="flex gap-2"><dt className="opacity-70 w-16">Fabric</dt><dd>{p.fabric}</dd></div>
          <div className="flex gap-2"><dt className="opacity-70 w-16">Fit</dt><dd>{p.fit}</dd></div>
          <div className="flex gap-2"><dt className="opacity-70 w-16">Care</dt><dd>Machine wash cold, line dry.</dd></div>
        </dl>
        <div className="mt-4">
          <span className="lbl">Size</span>
          <div className="flex gap-2 flex-wrap" role="radiogroup" aria-label="Size">
            {SIZES.map((s) => (
              <button
                key={s}
                role="radio"
                aria-checked={size === s}
                onClick={() => setSize(s)}
                className={`border rule px-4 py-2 ${size === s ? "bg-ink text-paper" : ""}`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-5 flex gap-3 items-center flex-wrap">
          <button
            className="btn btn-solid"
            onClick={() => {
              addLine(p.slug, size);
              setAdded(true);
              setTimeout(() => setAdded(false), 1500);
            }}
          >
            {added ? "In the bag ✓" : "Add to bag"}
          </button>
          <a href="/cart" className="btn">Bag →</a>
        </div>
        <details className="mt-6 border-t rule pt-4 text-sm">
          <summary className="cursor-pointer uppercase tracking-widest text-xs">Size guide</summary>
          <p className="mt-2 opacity-80">
            Chest, in inches, measured flat and doubled: XS 34 · S 36 · M 38 · L 40 · XL 42.
            Tees and hoodies are cut roomy — between sizes, take the smaller. Denim does not
            stretch; go by your trouser waist.
          </p>
        </details>
        {tryonOn && <TryOn productName={p.name} productSlug={p.slug} />}
      </div>
    </div>
  );
}
