"use server";
// Server actions: login, signup, logout, save setup. Cookie is httpOnly.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { api, postForm, sessionToken, ApiError } from "./api";

// ---- Hunts (shopping + construction) ----

export async function createHunt(form: FormData) {
  const token = await sessionToken();
  const flow = String(form.get("flow") || "shopping");
  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) redirect("/hunts?error=attach%20a%20photo%20or%20plan");
  const out = new FormData();
  out.append(flow === "construction" ? "plan" : "photo", file);
  out.append("flow", flow);
  for (const k of ["size", "budget", "city", "floors", "floor_height_ft", "finish", "builtup_sqft"]) {
    const v = form.get(k);
    if (v !== null && String(v) !== "") out.append(k, String(v));
  }
  let hid = "";
  try {
    const data = await postForm("/api/hunts", out, token);
    hid = String(data.id);
  } catch (e) {
    redirect(`/hunts?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/hunts/${hid}`);
}

export async function deleteHunt(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/hunts/${form.get("id")}`, { method: "DELETE" }, token);
  } catch (e) {
    redirect(`/hunts?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect("/hunts");
}

export async function confirmRooms(form: FormData) {
  // Inputs: name-{i}, length-{i}, width-{i}; unit-{i} hidden; count hidden.
  const token = await sessionToken();
  const n = Number(form.get("count") || 0);
  const rooms = [];
  for (let i = 0; i < n; i++) {
    const name = String(form.get(`name-${i}`) || "").trim();
    if (!name) continue;
    rooms.push({
      name,
      length: Number(form.get(`length-${i}`) || 0),
      width: Number(form.get(`width-${i}`) || 0),
      unit: String(form.get(`unit-${i}`) || "ft"),
    });
  }
  try {
    await api(`/api/hunts/${form.get("id")}/rooms`, {
      method: "PATCH",
      body: JSON.stringify({ rooms }),
    }, token);
  } catch (e) {
    redirect(`/hunts/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/hunts/${form.get("id")}`);
}

export async function buildBoq(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/hunts/${form.get("id")}/boq`, { method: "POST", body: "{}" }, token);
  } catch (e) {
    redirect(`/hunts/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/hunts/${form.get("id")}`);
}

export async function editBoqQty(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/hunts/${form.get("id")}/boq`, {
      method: "PATCH",
      body: JSON.stringify({ name: form.get("name"), quantity: Number(form.get("quantity")) }),
    }, token);
  } catch (e) {
    redirect(`/hunts/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/hunts/${form.get("id")}`);
}

export async function genImage(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/hunts/${form.get("id")}/image`, {
      method: "POST",
      body: JSON.stringify({ style: String(form.get("style") || "") }),
    }, token);
  } catch (e) {
    redirect(`/hunts/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/hunts/${form.get("id")}`);
}

export async function approveHunt(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/hunts/${form.get("id")}/approve`, {
      method: "POST",
      body: JSON.stringify({ image: String(form.get("image") || "") }),
    }, token);
  } catch (e) {
    redirect(`/hunts/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/hunts/${form.get("id")}`);
}

export async function startVendorSearch(form: FormData) {
  const token = await sessionToken();
  const ids = form.getAll("item").map(Number).filter(Boolean);
  try {
    await api(`/api/hunts/${form.get("id")}/vendors`, {
      method: "POST",
      body: JSON.stringify({ item_ids: ids.length ? ids : null }),
    }, token);
  } catch (e) {
    redirect(`/hunts/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/hunts/${form.get("id")}`);
}

// ---- Sellers ----

export async function addSeller(form: FormData) {
  const token = await sessionToken();
  if (!form.get("agreed")) redirect("/sellers?error=the%20opt-in%20checkbox%20is%20required");
  try {
    await api("/api/sellers", {
      method: "POST",
      body: JSON.stringify({
        name: String(form.get("name") || ""),
        phone: String(form.get("phone") || ""),
        kind: String(form.get("kind") || "shop"),
        agreed: true,
      }),
    }, token);
  } catch (e) {
    redirect(`/sellers?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect("/sellers");
}

export async function optOutSeller(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/sellers/${form.get("id")}`, {
      method: "PATCH",
      body: JSON.stringify({ opted_in: false }),
    }, token);
  } catch (e) {
    redirect(`/sellers?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect("/sellers");
}

function sentNote(r: any): string {
  if (r?.sent && r.sent !== "none") return "Sent on WhatsApp. Replies will appear here.";
  return r?.note || "The message was not sent.";
}

export async function stockCheck(form: FormData) {
  const token = await sessionToken();
  const listing = String(form.get("listing_id"));
  const hid = String(form.get("hunt_id"));
  let note = "";
  try {
    const r = await api(`/api/listings/${listing}/stock-check`, {
      method: "POST",
      body: JSON.stringify({ seller_id: Number(form.get("seller_id") || 0) || null }),
    }, token);
    note = sentNote(r);
  } catch (e) {
    redirect(`/hunts/${hid}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/hunts/${hid}?sent=${encodeURIComponent(note)}`);
}

export async function quoteRequest(form: FormData) {
  const token = await sessionToken();
  const listing = String(form.get("listing_id"));
  const hid = String(form.get("hunt_id"));
  let note = "";
  try {
    const r = await api(`/api/listings/${listing}/quote-request`, {
      method: "POST",
      body: JSON.stringify({ seller_id: Number(form.get("seller_id") || 0) || null }),
    }, token);
    note = sentNote(r);
  } catch (e) {
    redirect(`/hunts/${hid}?error=${encodeURIComponent(friendly(e))}#quotes`);
  }
  redirect(`/hunts/${hid}?sent=${encodeURIComponent(note)}#quotes`);
}

// A logged-in user says which opted-in vendor sells this listing.
export async function linkSeller(form: FormData) {
  const token = await sessionToken();
  const listing = Number(form.get("listing_id"));
  const hid = String(form.get("hunt_id"));
  const back = String(form.get("back") || "");
  try {
    await api(`/api/sellers/${form.get("seller_id")}/link`, {
      method: "POST",
      body: JSON.stringify({ listing_id: listing }),
    }, token);
  } catch (e) {
    redirect(`/hunts/${hid}?error=${encodeURIComponent(friendly(e))}`);
  }
  // Back to the same step: order screen, or the message preview.
  redirect(back.startsWith("/hunts/") ? back : `/hunts/${hid}?preview=${listing}#ask`);
}

const COOKIE = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  maxAge: 60 * 60 * 24 * 7,
  path: "/",
};

function friendly(e: unknown): string {
  return e instanceof ApiError ? e.message : "something went wrong";
}

export async function login(form: FormData) {
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
    });
    (await cookies()).set("session", data.token, COOKIE);
  } catch (e) {
    return { error: friendly(e) };
  }
  redirect("/hunts");
}

export async function signup(form: FormData) {
  try {
    const data = await api("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        business_name: form.get("business_name"),
        name: form.get("name"),
        email: form.get("email"),
        password: form.get("password"),
        signup_code: form.get("signup_code"),
      }),
    });
    (await cookies()).set("session", data.token, COOKIE);
  } catch (e) {
    return { error: friendly(e) };
  }
  redirect("/setup");
}

export async function logout() {
  const token = await sessionToken();
  if (token) {
    try {
      await api("/api/auth/logout", { method: "POST" }, token);
    } catch {
      // clearing the cookie is what matters
    }
  }
  (await cookies()).delete("session");
  redirect("/login");
}

export async function saveSetup(form: FormData) {
  const token = await sessionToken();
  const body = {
    name: form.get("name"),
    timezone: form.get("timezone"),
    slot_minutes: Number(form.get("slot_minutes")),
    seats_per_slot: Number(form.get("seats_per_slot")),
    greeting: form.get("greeting"),
    owner_whatsapp: form.get("owner_whatsapp"),
    wa_phone_number_id: form.get("wa_phone_number_id"),
    wa_display_number: form.get("wa_display_number"),
    delivery_name: form.get("delivery_name"),
    delivery_address: form.get("delivery_address"),
    delivery_phone: form.get("delivery_phone"),
    delivery_pref: form.get("delivery_pref"),
    delivery_date: form.get("delivery_date"),
    country: form.get("country"),
  };
  try {
    await api("/api/business", { method: "PUT", body: JSON.stringify(body) }, token);
  } catch (e) {
    redirect(`/setup?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect("/setup?saved=1");
}

export async function bookingMove(form: FormData) {
  const id = form.get("id");
  const date = form.get("date") ?? "";
  const token = await sessionToken();
  try {
    await api(`/api/bookings/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ slot: form.get("slot") }),
    }, token);
  } catch (e) {
    redirect(`/bookings?date=${date}&error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/bookings?date=${date}`);
}

export async function bookingCancel(form: FormData) {
  const id = form.get("id");
  const date = form.get("date") ?? "";
  const token = await sessionToken();
  try {
    await api(`/api/bookings/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "cancelled" }),
    }, token);
  } catch (e) {
    redirect(`/bookings?date=${date}&error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/bookings?date=${date}`);
}

export async function taskDone(form: FormData) {
  const id = form.get("id");
  const token = await sessionToken();
  try {
    await api(`/api/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "done", note: form.get("note") }),
    }, token);
  } catch (e) {
    redirect(`/tasks?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect("/tasks");
}

export async function callButton(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/contacts/${form.get("contact_id")}/call-button`, {
      method: "POST",
      body: JSON.stringify({}),
    }, token);
  } catch (e) {
    redirect(`/contacts/${form.get("contact_id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/contacts/${form.get("contact_id")}?sent=1`);
}

export async function aiCallback(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/contacts/${form.get("contact_id")}/callback`, {
      method: "POST",
      body: JSON.stringify({ purpose: "follow-up" }),
    }, token);
  } catch (e) {
    redirect(`/contacts/${form.get("contact_id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/contacts/${form.get("contact_id")}?sent=1`);
}

export async function updateContact(form: FormData) {
  const id = form.get("id");
  const token = await sessionToken();
  const tags = String(form.get("tags") ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  try {
    await api(`/api/contacts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: form.get("name"),
        stage: form.get("stage"),
        tags,
        notes: form.get("notes"),
      }),
    }, token);
  } catch (e) {
    redirect(`/contacts/${id}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/contacts/${id}?saved=1`);
}

// ---- Purchases (Picker suggestion shown on the order page; user can change) ----

export async function createPurchase(form: FormData) {
  const token = await sessionToken();
  const hid = String(form.get("hunt_id") || "");
  const listing = String(form.get("listing_id"));
  let pid = "";
  let problem = "";
  try {
    const r = await api("/api/purchases", {
      method: "POST",
      body: JSON.stringify({
        listing_id: Number(listing),
        price: form.get("price") === "" ? null : Number(form.get("price")),
        seller_id: Number(form.get("seller_id") || 0) || null,
        delivery_option: String(form.get("delivery_option") || ""),
        payment: String(form.get("payment") || "cod"),
      }),
    }, token);
    pid = String(r.purchase_id);
    if (r.sent === "none") problem = r.note || "The order did not reach the seller.";
  } catch (e) {
    redirect(`/hunts/${hid}/order/${listing}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(problem ? `/orders/${pid}?error=${encodeURIComponent(problem)}` : `/orders/${pid}`);
}

export async function cancelPurchase(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/purchases/${form.get("id")}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "cancelled" }),
    }, token);
  } catch (e) {
    redirect(`/orders/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/orders/${form.get("id")}`);
}

export async function markDelivered(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/purchases/${form.get("id")}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "delivered" }),
    }, token);
  } catch (e) {
    redirect(`/orders/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/orders/${form.get("id")}`);
}

export async function askForUpdate(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/purchases/${form.get("id")}/ask-update`, {
      method: "POST",
      body: JSON.stringify({}),
    }, token);
  } catch (e) {
    redirect(`/orders/${form.get("id")}?error=${encodeURIComponent(friendly(e))}`);
  }
  redirect(`/orders/${form.get("id")}?asked=1`);
}
