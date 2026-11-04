"use client";
// Login form: server action sets the httpOnly cookie, else shows the error.
import { useState } from "react";
import { login } from "@/lib/actions";
import Submit from "@/lib/submit";

export default function LoginPage() {
  const [error, setError] = useState("");
  return (
    <div className="auth">
      <section className="auth-copy">
        <h1>Send the agents shopping.</h1>
        <p>
          Drop a photo or a floor plan. They find vendors, check real prices, and ask on WhatsApp
          when you say so.
        </p>
      </section>
      <main className="auth-form">
        <h2>Log in</h2>
        <form
          action={async (fd) => {
            const res = await login(fd);
            if (res?.error) setError(res.error);
          }}
        >
          <label>
            Email
            <input className="input" name="email" type="email" required autoComplete="username" />
          </label>
          <label>
            Password
            <input className="input" name="password" type="password" required autoComplete="current-password" />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <Submit pending="Logging in…">Log in</Submit>
        </form>
      </main>
    </div>
  );
}
