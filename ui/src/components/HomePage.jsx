// Copyright (c) 2026 John Carter. All rights reserved.
import React from "react";
import { BrainCircuit, Plug, ShieldCheck, Users } from "lucide-react";
import { useNavigate } from "react-router-dom";

const FEATURES = [
  {
    icon: BrainCircuit,
    title: "Persistent memory across sessions",
    body: "Store facts, context, and decisions once. Every Claude session picks up exactly where the last one left off.",
  },
  {
    icon: Plug,
    title: "Works with any MCP client",
    body: "Plug in to Claude Code, Claude Desktop, or any agent that speaks the Model Context Protocol.",
  },
  {
    icon: Users,
    title: "Share memory across your team",
    body: "One Hive, many agents. Team members and automated workflows read from the same memory store.",
  },
  {
    icon: ShieldCheck,
    title: "Your data, scoped to you",
    body: "Each user sees only their own memories and clients. Admins get a full view. OAuth 2.1 throughout.",
  },
];

const HOW_IT_WORKS = [
  {
    step: "1",
    title: "Sign in with Google",
    body: "Create your free account in seconds — no credit card, no deployment.",
  },
  {
    step: "2",
    title: "Register an MCP client",
    body: "Give your agent a name and copy the one-line config snippet into Claude Code.",
  },
  {
    step: "3",
    title: "Start remembering",
    body: 'Tell Claude to "remember" something. Hive stores it. Every future session can recall it.',
  },
];

export default function HomePage() {
  const navigate = useNavigate();

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", color: "#1a1a2e" }}>
      {/* Nav */}
      <header style={{ background: "#1a1a2e", color: "#fff" }}>
        <div
          style={{
            maxWidth: 1100,
            margin: "0 auto",
            padding: "0 32px",
            height: 56,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <img src="/logo.svg" alt="Hive" style={{ height: 28 }} />
            <span style={{ fontWeight: 700, fontSize: 20, letterSpacing: 1 }}>Hive</span>
          </span>
          <button
            onClick={() => navigate("/app")}
            style={{
              background: "transparent",
              color: "rgba(255,255,255,.8)",
              border: "1px solid rgba(255,255,255,.3)",
              borderRadius: 6,
              padding: "6px 16px",
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            Sign in
          </button>
        </div>
      </header>

      {/* Hero */}
      <section
        style={{
          background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%)",
          color: "#fff",
          padding: "96px 32px",
          textAlign: "center",
        }}
      >
        <h1
          style={{
            fontSize: "clamp(2rem, 5vw, 3.5rem)",
            fontWeight: 800,
            marginBottom: 24,
            lineHeight: 1.15,
          }}
        >
          Persistent memory
          <br />
          for Claude agents
        </h1>
        <p
          style={{
            fontSize: "clamp(1rem, 2vw, 1.25rem)",
            color: "rgba(255,255,255,.75)",
            maxWidth: 560,
            margin: "0 auto 40px",
            lineHeight: 1.6,
          }}
        >
          Hive gives your Claude agents a shared, durable memory store via the Model Context
          Protocol — so context survives across sessions, tools, and team members.
        </p>
        <button
          onClick={() => navigate("/app")}
          style={{
            background: "#e8a020",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "14px 36px",
            fontSize: 17,
            fontWeight: 600,
            cursor: "pointer",
            letterSpacing: 0.3,
          }}
        >
          Get started free →
        </button>
        <p style={{ marginTop: 16, color: "rgba(255,255,255,.45)", fontSize: 13 }}>
          No credit card required
        </p>
      </section>

      {/* Features */}
      <section style={{ padding: "80px 32px" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <h2
          style={{ textAlign: "center", fontSize: "1.75rem", fontWeight: 700, marginBottom: 56 }}
        >
          Everything your agents need to remember
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 32,
          }}
        >
          {FEATURES.map((f) => (
            <div
              key={f.title}
              style={{
                background: "#fff",
                border: "1px solid #e8e8e8",
                borderRadius: 12,
                padding: 28,
                boxShadow: "0 2px 8px rgba(0,0,0,.04)",
              }}
            >
              <div style={{ marginBottom: 12 }}><f.icon size={32} color="#e8a020" /></div>
              <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: 8 }}>{f.title}</h3>
              <p style={{ color: "#555", fontSize: 14, lineHeight: 1.6 }}>{f.body}</p>
            </div>
          ))}
        </div>
        </div>
      </section>

      {/* How it works */}
      <section style={{ background: "#f8f9fa", padding: "80px 32px" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <h2
            style={{
              textAlign: "center",
              fontSize: "1.75rem",
              fontWeight: 700,
              marginBottom: 56,
            }}
          >
            Up and running in minutes
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
            {HOW_IT_WORKS.map((s) => (
              <div key={s.step} style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: "50%",
                    background: "#1a1a2e",
                    color: "#fff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 700,
                    fontSize: 16,
                    flexShrink: 0,
                  }}
                >
                  {s.step}
                </div>
                <div>
                  <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: 6 }}>
                    {s.title}
                  </h3>
                  <p style={{ color: "#555", fontSize: 14, lineHeight: 1.6 }}>{s.body}</p>
                </div>
              </div>
            ))}
          </div>
          <div style={{ textAlign: "center", marginTop: 56 }}>
            <button
              onClick={() => navigate("/app")}
              style={{
                background: "#1a1a2e",
                color: "#fff",
                border: "none",
                borderRadius: 8,
                padding: "14px 36px",
                fontSize: 16,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Get started free →
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: "1px solid #eee" }}>
        <div
          style={{
            maxWidth: 1100,
            margin: "0 auto",
            padding: "32px",
            textAlign: "center",
            fontSize: 13,
            color: "#999",
          }}
        >
          © 2026 Hive. Free to use.
        </div>
      </footer>
    </div>
  );
}
