import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import type { UserResponse } from "../api/client";
import { ApiError, login } from "../api/client";

/**
 * Minimal login gate for the M1 walking-skeleton demo (issue #44). The SPA
 * has no session-restoration or logout UI yet — those belong to a proper
 * auth screen, out of scope here; this exists only so the search page below
 * it has something to authenticate against in a real browser.
 */
export function LoginForm({ onLoggedIn }: { onLoggedIn: (user: UserResponse) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: onLoggedIn,
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate({ username, password });
      }}
    >
      <h2>Sign in</h2>
      <label>
        Username
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
      </label>
      <label>
        Password
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      <button type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? "Signing in…" : "Sign in"}
      </button>
      {mutation.isError && (
        <p role="alert">
          {mutation.error instanceof ApiError && mutation.error.status === 401
            ? "Invalid username or password."
            : "Sign in failed."}
        </p>
      )}
    </form>
  );
}
