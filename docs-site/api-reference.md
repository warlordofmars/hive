---
title: API reference
outline: deep
---

<script setup>
import { onMounted } from "vue";

onMounted(() => {
  const existing = document.getElementById("scalar-api-reference");
  if (existing) return;
  const script = document.createElement("script");
  script.id = "scalar-api-reference";
  script.src = "https://cdn.jsdelivr.net/npm/@scalar/api-reference";
  script.setAttribute("data-url", "/docs/openapi.json");
  script.setAttribute("data-configuration", JSON.stringify({
    theme: "purple",
    hideDownloadButton: false,
    layout: "classic",
  }));
  document.getElementById("hive-api-reference").appendChild(script);
});
</script>

# API reference

Every endpoint the Hive management API exposes, generated straight from the deployed FastAPI app. Use it alongside the [MCP tools reference](/tools/overview) if you're building SDKs or bots against the REST surface.

<div id="hive-api-reference"></div>
