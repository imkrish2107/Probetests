"use client";

import { useEffect, useState } from "react";
import { api, type OrderItem } from "@/lib/api";

type Status = {
  id: number;
  status: string;
  total: string;
  items: OrderItem[];
  whatsapp: string;
};

const NEXT: Record<string, string> = {
  pending_call: "Waiting for your confirmation — check WhatsApp, or confirm below.",
  needs_followup: "We nudged you on WhatsApp — confirm below before we shelve it.",
  confirmed: "Confirmed. We ship in 2–3 days, cash on delivery.",
  change_requested: "Change noted — the team will call you about it.",
  cancelled: "Cancelled. The rail is still here when you want it.",
  shipped: "Shipped. The courier takes cash.",
  delivered: "Delivered. Wear it out.",
};

export default function OrderPage({
  params,
  searchParams,
}: {
  params: { id: string };
  searchParams: { phone?: string; fresh?: string };
}) {
  const [phone, setPhone] = useState(searchParams.phone || "");
  const [o, setO] = useState<Status | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(ph: string) {
    setErr("");
    try {
      setO(await api.orderStatus(Number(params.id), ph));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Lookup failed.");
    }
  }

  useEffect(() => {
    if (searchParams.phone) load(searchParams.phone);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function act(action: string) {    setBusy(true);
    setErr("");
    try {
      const r = await api.orderAction(Number(params.id), { phone, action });
      setO(await api.orderStatus(Number(params.id), phone));
      void r;
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Update failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fade-in py-10 max-w-2xl">
      {searchParams.fresh === "1" && (
        <div className="border rule p-4 mb-6">
          <p className="font-display text-2xl">Order placed.</p>
          <p className="text-sm mt-1 opacity-80">
            Open WhatsApp and send <strong>ORDER {params.id}</strong> to confirm — or confirm
            right here with your phone number.
          </p>
          <a
            className="btn btn-solid mt-3"
            href={o?.whatsapp || `https://wa.me/?text=${encodeURIComponent(`ORDER ${params.id}`)}`}
          >
            Confirm on WhatsApp
          </a>
        </div>
      )}
      <h1 className="font-display text-4xl">Order #{params.id}</h1>
      {!o ? (
        <div className="mt-4">
          <label className="lbl" htmlFor="ph">Order phone (with country code)</label>
          <div className="flex gap-2">
            <input
              id="ph"
              className="field"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+91…"
              autoComplete="tel"
            />
            <button className="btn" onClick={() => load(phone)}>Look up</button>
          </div>
          {err && <p className="mt-2 text-sm text-oxblood">{err}</p>}
        </div>
      ) : (
        <div className="mt-4">
          <p className="uppercase tracking-widest text-sm text-oxblood">{o.status.replace("_", " ")}</p>
          <p className="mt-1">{NEXT[o.status] || o.status}</p>
          <ul className="border-t rule mt-4 pt-3 space-y-1">
            {o.items.map((i, k) => (
              <li key={k} className="flex justify-between">
                <span>{i.qty}x {i.name} ({i.size})</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xl">{o.total} · cash on delivery</p>
          {(o.status === "pending_call" || o.status === "needs_followup") && (
            <div className="flex gap-3 mt-4 flex-wrap">
              <button className="btn btn-solid" disabled={busy} onClick={() => act("confirmed")}>Confirm</button>
              <button className="btn" disabled={busy} onClick={() => act("change_requested")}>Change</button>
              <button className="btn" disabled={busy} onClick={() => act("cancelled")}>Cancel</button>
            </div>
          )}
          {err && <p className="mt-2 text-sm text-oxblood">{err}</p>}
        </div>
      )}
    </div>
  );
}
