// Copyright (c) 2026 John Carter. All rights reserved.
import React from "react";

export default function LoginPage() {
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
        <button
          onClick={() => {
            window.location.href = "/auth/login";
          }}
          style={{
            width: "100%",
            padding: "12px 0",
            background: "#fff",
            border: "1px solid #ddd",
            borderRadius: 8,
            cursor: "pointer",
            fontSize: 15,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
          }}
        >
          Sign in with Google
        </button>
      </div>
    </div>
  );
}
