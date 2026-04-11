// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useState } from "react";
import { Loader2 } from "lucide-react";

function GoogleIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  );
}

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const errorParam = new URLSearchParams(globalThis.location.search).get("error");

  function handleSignIn() {
    setLoading(true);
    globalThis.location.href = "/auth/login";
  }

  return (
    <>
      <style>{`@keyframes hive-spin { to { transform: rotate(360deg); } }`}</style>
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg)",
        }}
      >
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            padding: 48,
            textAlign: "center",
            boxShadow: "0 2px 16px rgba(0,0,0,.1)",
            maxWidth: 400,
            width: "100%",
          }}
        >
          <img src="/logo.svg" alt="Hive" style={{ width: 64, height: 64, marginBottom: 16 }} />
          <p style={{ color: "var(--text-muted)", marginBottom: 32 }}>
            Shared persistent memory for AI agents
          </p>
          <button
            onClick={handleSignIn}
            disabled={loading}
            style={{
              width: "100%",
              padding: "12px 0",
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              cursor: loading ? "default" : "pointer",
              fontSize: 15,
              color: "var(--text)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? (
              <>
                <Loader2 size={16} style={{ animation: "hive-spin 1s linear infinite" }} />
                Redirecting…
              </>
            ) : (
              <>
                <GoogleIcon />
                Sign in with Google
              </>
            )}
          </button>
          {errorParam && (
            <p style={{ color: "var(--danger)", marginTop: 12, fontSize: 14 }}>
              Sign in was cancelled. Please try again.
            </p>
          )}
          <a
            href="/"
            style={{
              display: "inline-block",
              marginTop: 24,
              fontSize: 13,
              color: "var(--text-muted)",
              textDecoration: "none",
            }}
          >
            ← Back to home
          </a>
        </div>
      </div>
    </>
  );
}
