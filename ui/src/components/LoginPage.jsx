// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useState } from "react";

const CLIENT_SCOPE = "memories:read memories:write clients:read clients:write";

function base64urlEncode(buffer) {
  return btoa(String.fromCharCode(...new Uint8Array(buffer)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

async function generatePKCE() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  const verifier = base64urlEncode(array.buffer);
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const challenge = base64urlEncode(hash);
  return { verifier, challenge };
}

async function getOrRegisterClientId() {
  const stored = localStorage.getItem("hive_client_id");
  if (stored) return stored;

  const redirectUri = `${window.location.origin}/oauth/callback`;
  const res = await fetch("/oauth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_name: "Hive Management UI",
      redirect_uris: [redirectUri],
      scope: CLIENT_SCOPE,
    }),
  });
  if (!res.ok) throw new Error("Failed to register UI client");
  const data = await res.json();
  localStorage.setItem("hive_client_id", data.client_id);
  return data.client_id;
}

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function signInWithGoogle() {
    setLoading(true);
    setError(null);
    try {
      const clientId = await getOrRegisterClientId();
      const { verifier, challenge } = await generatePKCE();
      const redirectUri = `${window.location.origin}/oauth/callback`;
      const stateArr = new Uint8Array(16);
      crypto.getRandomValues(stateArr);
      const state = base64urlEncode(stateArr.buffer);

      sessionStorage.setItem("pkce_verifier", verifier);
      sessionStorage.setItem("oauth_state", state);

      const params = new URLSearchParams({
        response_type: "code",
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: CLIENT_SCOPE,
        code_challenge: challenge,
        code_challenge_method: "S256",
        state,
      });
      window.location.href = `/oauth/authorize?${params}`;
    } catch (e) {
      setError(e.message);
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#f5f5f5",
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 12,
          padding: 48,
          textAlign: "center",
          boxShadow: "0 2px 16px rgba(0,0,0,.1)",
          maxWidth: 400,
          width: "100%",
        }}
      >
        <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 8, color: "#1a1a2e" }}>
          Hive
        </h1>
        <p style={{ color: "#666", marginBottom: 32 }}>
          Shared persistent memory for Claude agents
        </p>
        {error && (
          <p style={{ color: "#d00", marginBottom: 16, fontSize: 14 }}>{error}</p>
        )}
        <button
          onClick={signInWithGoogle}
          disabled={loading}
          style={{
            width: "100%",
            padding: "12px 0",
            background: "#fff",
            border: "1px solid #ddd",
            borderRadius: 8,
            cursor: loading ? "not-allowed" : "pointer",
            fontSize: 15,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? "Redirecting…" : "Sign in with Google"}
        </button>
      </div>
    </div>
  );
}
