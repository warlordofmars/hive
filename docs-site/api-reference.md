---
title: API reference
outline: deep
---

<script setup>
import { onMounted } from "vue";

onMounted(() => {
  // Load Redoc once, then initialise it into the #redoc-container div.
  // Using Redoc.init() avoids VitePress/Vue stripping the custom <redoc>
  // web-component element during build.
  function mount() {
    if (window.Redoc && document.getElementById("redoc-container")) {
      window.Redoc.init(
        "/docs/openapi.json",
        { theme: { colors: { primary: { main: "#e8a020" } } } },
        document.getElementById("redoc-container"),
      );
    }
  }

  if (window.Redoc) {
    mount();
    return;
  }
  const existing = document.getElementById("redoc-standalone");
  if (existing) {
    existing.addEventListener("load", mount, { once: true });
    return;
  }
  const script = document.createElement("script");
  script.id = "redoc-standalone";
  script.src = "https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js";
  script.addEventListener("load", mount, { once: true });
  document.body.appendChild(script);
});
</script>

# API reference

Every endpoint the Hive management API exposes, auto-generated from the deployed FastAPI app. Use it alongside the [MCP tools reference](/tools/overview) if you're building SDKs or bots against the REST surface.

<div id="redoc-container"></div>
