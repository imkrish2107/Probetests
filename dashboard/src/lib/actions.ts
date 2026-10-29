"use server";
// Server actions: login, signup, logout, save setup. Cookie is httpOnly.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { api, sessionToken, ApiError } from "./api";

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
    cookies().set("session", data.token, COOKIE);
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
    cookies().set("session", data.token, COOKIE);
  } catch (e) {
    return { error: friendly(e) };
  }
  redirect("/setup");
}

export async function logout() {
  const token = sessionToken();
  if (token) {
    try {
      await api("/api/auth/logout", { method: "POST" }, token);
    } catch {
      // clearing the cookie is what matters
    }
  }
  cookies().delete("session");
  redirect("/login");
}

export async function saveSetup(form: FormData) {
  const token = sessionToken();
  const body = {
    name: form.get("name"),
    timezone: form.get("timezone"),
    slot_minutes: Number(form.get("slot_minutes")),
    seats_per_slot: Number(form.get("seats_per_slot")),
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
  const token = sessionToken();
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
  const token = sessionToken();
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
  const token = sessionToken();
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
  const token = sessionToken();
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
  const token = sessionToken();
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
  const token = sessionToken();
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
