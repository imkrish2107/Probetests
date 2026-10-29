"use client";
// Login form: server action sets the httpOnly cookie, else shows the error.
import { useState } from "react";
import { login } from "@/lib/actions";

export default function LoginPage() {
  const [error, setError] = useState("");
  return (
    <main>
      <div className="card">
        <h1>Log in</h1>
        <form
          action={async (fd) => {
            const res = await login(fd);
            if (res?.error) setError(res.error);
          }}
        >
          <label>
            Email
            <input className="input" name="email" type="email" required />
          </label>
          <label>
            Password
            <input className="input" name="password" type="password" required />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn" type="submit">
            Log in
          </button>
        </form>
        <p>
          No account? <a href="/signup">Sign up</a>
        </p>
      </div>
    </main>
  );
}
