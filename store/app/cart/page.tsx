"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, inr, type Product } from "@/lib/api";
import { readCart, writeCart, type CartLine } from "@/lib/cart";

export default function Cart() {
  const router = useRouter();
  const [products, setProducts] = useState<Product[]>([]);
  const [lines, setLines] = useState<CartLine[]>([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [consent, setConsent] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setLines(readCart());
    api.products().then(({ items }) => setProducts(items)).catch(() => {});
  }, []);

  const bySlug = Object.fromEntries(products.map((p) => [p.slug, p]));
  const valid = lines.filter((l) => bySlug[l.slug]);
  const total = valid.reduce((s, l) => s + bySlug[l.slug].price_paise * l.qty, 0);

  function setQty(i: number, qty: number) {
    const next = valid.map((l, j) => (j === i ? { ...l, qty } : l)).filter((l) => l.qty > 0);
    setLines(next);
    writeCart(next);
  }

  // The store API takes product ids; resolve slugs here so checkout sends ids.
  async function checkoutWithIds() {
    const { items } = await api.products();
    const idBySlug = Object.fromEntries(items.map((p) => [p.slug, p.id]));
    const bodyItems = valid.map((l) => ({
      product_id: idBySlug[l.slug] ?? 0,
      qty: l.qty,
      size: l.size,
    }));
    return checkoutRaw(bodyItems);
  }

  async function checkoutRaw(bodyItems: { product_id: number; qty: number; size: string }[]) {
    setErr("");
    if (!name.trim() || digits(phone).length < 7 || address.trim().length < 8) {
      setErr("Name, a full phone number with country code, and a full address are needed.");
      return;
    }
    if (!consent) {
      setErr("Please consent to the confirmation call — every order is confirmed before shipping.");
      return;
    }
    setBusy(true);
    try {
      const o = await api.createOrder({
        items: bodyItems,
        name: name.trim(),
        phone: phone.trim(),
        address: address.trim(),
        call_consent: true,
      });
      writeCart([]);
      router.push(`/order/${o.id}?phone=${encodeURIComponent(phone.trim())}&fresh=1`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Order failed.");
    } finally {
      setBusy(false);
    }
  }

  function digits(s: string) {
    return s.replace(/\D/g, "");
  }

  if (!valid.length)
    return (
      <div className="py-16">
        <h1 className="font-display text-4xl">Your bag is empty</h1>
        <p className="mt-3"><a href="/shop" className="btn">Back to the rail</a></p>
      </div>
    );

  return (
    <div className="fade-in py-10 grid grid-cols-12 gap-6">
      <div className="col-span-12 md:col-span-6">
        <h1 className="font-display text-4xl mb-4">Your bag</h1>
        {valid.map((l, i) => (
          <div key={`${l.slug}-${l.size}`} className="flex gap-4 border-t rule py-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/products/${bySlug[l.slug].image}`} alt="" className="w-20 aspect-[3/4] object-cover border rule" />
            <div className="flex-1">
              <p className="font-medium">{bySlug[l.slug].name} · {l.size}</p>
              <p className="text-sm opacity-70">{inr(bySlug[l.slug].price_paise)} each</p>
              <div className="flex gap-2 items-center mt-2">
                <button aria-label="decrease" className="border rule px-2" onClick={() => setQty(i, l.qty - 1)}>−</button>
                <span>{l.qty}</span>
                <button aria-label="increase" className="border rule px-2" onClick={() => setQty(i, Math.min(9, l.qty + 1))}>+</button>
              </div>
            </div>
          </div>
        ))}
        <p className="border-t rule pt-3 text-xl">Total: {inr(total)} <span className="text-sm opacity-70">· cash on delivery</span></p>
      </div>
      <div className="col-span-12 md:col-span-5 md:col-start-8">
        <h2 className="font-display text-2xl mb-4">Checkout</h2>
        <div className="space-y-3">
          <div><label className="lbl" htmlFor="nm">Name</label><input id="nm" className="field" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></div>
          <div><label className="lbl" htmlFor="ph">Phone (with country code)</label><input id="ph" className="field" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91…" autoComplete="tel" /></div>
          <div><label className="lbl" htmlFor="ad">Delivery address</label><textarea id="ad" className="field" rows={3} value={address} onChange={(e) => setAddress(e.target.value)} autoComplete="street-address" /></div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1" />
            I agree to a confirmation call or WhatsApp message about this order before it ships.
          </label>
          {err && <p className="text-sm text-oxblood">{err}</p>}
          <button className="btn btn-solid" onClick={checkoutWithIds} disabled={busy}>
            {busy ? "Placing…" : "Place order"}
          </button>
        </div>
      </div>
    </div>
  );
}
