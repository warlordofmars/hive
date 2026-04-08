// Copyright (c) 2026 John Carter. All rights reserved.
import React from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";

export default function PageLayout({ children }) {
  const navigate = useNavigate();

  return (
    <div className="font-[system-ui,sans-serif] text-[var(--text)] flex flex-col min-h-screen">
      {/* Nav */}
      <header className="bg-navy text-white">
        <div className="max-w-[1100px] mx-auto px-8 h-14 flex items-center justify-between">
          <span
            className="flex items-center gap-2 cursor-pointer"
            onClick={() => navigate("/")}
          >
            <img src="/logo.svg" alt="Hive" className="h-7 w-auto" />
            <span className="font-bold text-xl tracking-[1px]">Hive</span>
          </span>
          <div className="flex items-center gap-6">
            <a href="/use-cases" className="text-white/75 text-sm no-underline hover:text-white transition-colors">Use cases</a>
            <a href="/clients" className="text-white/75 text-sm no-underline hover:text-white transition-colors">Clients</a>
            <a href="/pricing" className="text-white/75 text-sm no-underline hover:text-white transition-colors">Pricing</a>
            <a href="/faq" className="text-white/75 text-sm no-underline hover:text-white transition-colors">FAQ</a>
            <a href="/docs/" className="text-white/75 text-sm no-underline hover:text-white transition-colors">Docs</a>
            <Button variant="outline" size="sm" onClick={() => navigate("/app")}>
              Sign in
            </Button>
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-[var(--border)]">
        <div className="max-w-[1100px] mx-auto px-8 py-8">
          <div className="flex flex-col gap-6 sm:flex-row sm:justify-between sm:items-start">
            <div className="flex items-center gap-2">
              <img src="/logo.svg" alt="Hive" className="h-5 w-auto opacity-60" />
              <span className="font-bold text-sm tracking-[1px] text-[var(--text-muted)]">Hive</span>
            </div>
            <div className="flex gap-8 text-sm text-[var(--text-muted)]">
              <a href="/use-cases" className="no-underline hover:text-[var(--text)] transition-colors">Use cases</a>
              <a href="/clients" className="no-underline hover:text-[var(--text)] transition-colors">Clients</a>
              <a href="/pricing" className="no-underline hover:text-[var(--text)] transition-colors">Pricing</a>
              <a href="/faq" className="no-underline hover:text-[var(--text)] transition-colors">FAQ</a>
              <a href="/docs/" className="no-underline hover:text-[var(--text)] transition-colors">Docs</a>
            </div>
          </div>
          <p className="mt-6 text-[13px] text-[var(--text-muted)]">© 2026 Hive. Free to use.</p>
        </div>
      </footer>
    </div>
  );
}
