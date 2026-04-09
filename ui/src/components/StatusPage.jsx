// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useEffect, useState } from "react";
import { CheckCircle, AlertCircle, RefreshCw } from "lucide-react";
import PageLayout from "@/components/PageLayout";

const CHECK_URL = "/health";

function useHealthCheck() {
  const [status, setStatus] = useState("loading"); // "loading" | "ok" | "error"
  const [version, setVersion] = useState(null);
  const [checkedAt, setCheckedAt] = useState(null);

  function check() {
    setStatus("loading");
    fetch(CHECK_URL)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setVersion(data.version ?? null);
        setStatus("ok");
        setCheckedAt(new Date());
      })
      .catch(() => {
        setStatus("error");
        setCheckedAt(new Date());
      });
  }

  useEffect(() => {
    check();
  }, []);

  return { status, version, checkedAt, check };
}

export default function StatusPage() {
  const { status, version, checkedAt, check } = useHealthCheck();

  const isOk = status === "ok";
  const isLoading = status === "loading";

  return (
    <PageLayout>
      {/* Header */}
      <section className="py-20 px-8 text-center bg-[var(--surface)]">
        <div className="max-w-[1100px] mx-auto">
          <h1 className="text-[2.5rem] font-extrabold mb-4">Service status</h1>
          <p className="text-[var(--text-muted)] text-lg max-w-[480px] mx-auto leading-relaxed">
            Current status of the Hive API.
          </p>
        </div>
      </section>

      {/* Status card */}
      <section className="py-16 px-8">
        <div className="max-w-[480px] mx-auto">
          <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-8">
            <div className="flex items-center gap-4 mb-6">
              {isLoading ? (
                <RefreshCw size={32} className="text-[var(--text-muted)] animate-spin" />
              ) : isOk ? (
                <CheckCircle size={32} className="text-green-500" />
              ) : (
                <AlertCircle size={32} className="text-red-500" />
              )}
              <div>
                <p className="font-bold text-lg">
                  {isLoading ? "Checking…" : isOk ? "All systems operational" : "Service unavailable"}
                </p>
                {version && (
                  <p className="text-sm text-[var(--text-muted)]">Version {version}</p>
                )}
              </div>
            </div>

            <div className="border-t border-[var(--border)] pt-4 flex items-center justify-between">
              {checkedAt ? (
                <p className="text-xs text-[var(--text-muted)]">
                  Checked at {checkedAt.toLocaleTimeString()}
                </p>
              ) : (
                <span />
              )}
              <button
                onClick={check}
                disabled={isLoading}
                className="flex items-center gap-1.5 text-xs text-brand hover:opacity-80 transition-opacity bg-transparent disabled:opacity-40"
              >
                <RefreshCw size={12} />
                Refresh
              </button>
            </div>
          </div>

          <p className="text-center text-xs text-[var(--text-muted)] mt-6">
            This page checks the Hive API in real time. For incident history, see our{" "}
            <a
              href="https://github.com/warlordofmars/hive/issues"
              className="text-brand no-underline hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              GitHub issues
            </a>
            .
          </p>
        </div>
      </section>
    </PageLayout>
  );
}
