"use client";
// Signup: creates the business + owner, lands on /setup.
import { useState } from "react";
import { signup } from "@/lib/actions";

export default function SignupPage() {
  const [error, setError] = useState("");
  return (
    <main>
      <div className="card">
        <h1>Sign up</h1>
        <form
          action={async (fd) => {
            const res = await signup(fd);
            if (res?.error) setError(res.error);
          }}
        >
          <label>
            Business name
            <input className="input" name="business_name" required />
          </label>
          <label>
            Your name
            <input className="input" name="name" required />
          </label>
          <label>
            Email
            <input className="input" name="email" type="email" required />
          </label>
          <label>
            Password (8+ characters)
            <input className="input" name="password" type="password" minLength={8} required />
          </label>
          <label>
            Signup code
            <input className="input" name="signup_code" required />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn" type="submit">
            Sign up
          </button>
        </form>
        <p>
          Have an account? <a href="/login">Log in</a>
        </p>
      </div>
    </main>
  );
}
