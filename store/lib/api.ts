const BASE =
  (process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");

export type Product = {
  id: number;
  slug: string;
  name: string;
  price_paise: number;
  image: string;
  fabric: string;
  fit: string;
  sizes: string;
};

export type OrderItem = { name: string; price_paise: number; qty: number; size: string };

async function req(path: string, init?: RequestInit) {
  const r = await fetch(`${BASE}${path}`, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as { error?: { message?: string } }).error?.message || `request failed (${r.status})`);
  return data;
}

export const api = {
  products: (): Promise<{ items: Product[] }> => req(`/api/public/products?slug=escape`),
  createOrder: (body: object) =>
    req(`/api/public/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: "escape", ...body }),
    }),
  orderStatus: (id: number, phone: string) =>
    req(`/api/public/orders/${id}?slug=escape&phone=${encodeURIComponent(phone)}`),
  orderAction: (id: number, body: object) =>
    req(`/api/public/orders/${id}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: "escape", ...body }),
    }),
  tryon: async (photo: Blob, product: string) => {
    const form = new FormData();
    form.append("consent", "1");
    form.append("product", product);
    form.append("photo", photo, "photo.jpg");
    const r = await fetch(`${BASE}/api/public/tryon`, { method: "POST", body: form });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error?.message || `preview failed (${r.status})`);
    return data as { id: string };
  },
  tryonUrl: (id: string) => `${BASE}/api/public/tryon/${id}`,
};

export function inr(paise: number) {
  return `₹${(paise / 100).toLocaleString("en-IN")}`;
}
