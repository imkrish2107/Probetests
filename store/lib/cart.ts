"use client";

export type CartLine = { slug: string; size: string; qty: number };

const KEY = "escape-cart";

export function readCart(): CartLine[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "[]");
  } catch {
    return [];
  }
}

export function writeCart(lines: CartLine[]) {
  localStorage.setItem(KEY, JSON.stringify(lines));
}

export function addLine(slug: string, size: string) {
  const lines = readCart();
  const found = lines.find((l) => l.slug === slug && l.size === size);
  if (found) found.qty = Math.min(9, found.qty + 1);
  else lines.push({ slug, size, qty: 1 });
  writeCart(lines);
}
