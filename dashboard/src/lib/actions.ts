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
  if (!(file instanceof File) || file.size === 0) return { error: "attach a photo or plan" };
  const out = new FormData();
  out.append(flow === "construction" ? "plan" : "photo", file);
  out.append("flow", flow);
  for (const k of ["size", "budget", "city", "floors", "floor_height_ft", "finish", "builtup_sqft"]) {
    const v = form.get(k);
    if (v !== null && String(v) !== "") out.append(k, String(v));
  }
  try {
    const data = await postForm("/api/hunts", out, token);
    redirect(`/hunts/${data.id}`);
  } catch (e) {
    return { error: friendly(e) };
  }
}

export async function deleteHunt(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/hunts/${form.get("id")}`, { method: "DELETE" }, token);
  } catch (e) {
    return { error: friendly(e) };
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
    return { error: friendly(e) };
  }
  redirect(`/hunts/${form.get("id")}`);
}

export async function buildBoq(form: FormData) {
  const token = await sessionToken();
  try {
    await api(`/api/hunts/${form.get("id")}/boq`, { method: "POST", body: "{}" }, token);
  } catch (e) {
    return { error: friendly(e) };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
  }
  redirect(`/hunts/${form.get("id")}`);
}

// ---- Sellers ----

export async function addSeller(form: FormData) {
  const token = await sessionToken();
  if (!form.get("agreed")) return { error: "the opt-in checkbox is required" };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
  }
  redirect("/sellers");
}

export async function stockCheck(form: FormData) {
  // Two-step: without send=1, shows the exact message first; with it, sends.
  const token = await sessionToken();
  const listing = String(form.get("listing_id"));
  const hid = String(form.get("hunt_id"));
  try {
    await api(`/api/listings/${listing}/stock-check`, {
      method: "POST",
      body: JSON.stringify({
        seller_id: Number(form.get("seller_id") || 0) || null,
        preview: !form.get("send"),
      }),
    }, token);
  } catch (e) {
    return { error: friendly(e) };
  }
  redirect(form.get("send") ? `/hunts/${hid}` : `/hunts/${hid}?preview=${listing}`);
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
  redirect("/");
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
  };
  try {
    await api("/api/business", { method: "PUT", body: JSON.stringify(body) }, token);
  } catch (e) {
    return { error: friendly(e) };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
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
    return { error: friendly(e) };
  }
  redirect(`/contacts/${id}?saved=1`);
}
