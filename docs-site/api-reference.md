---
title: API reference
outline: deep
---

<script setup>
import { onMounted, onBeforeUnmount } from "vue";

const SCRIPT_ID = "redoc-standalone";
const CONTAINER_ID = "redoc-container";
const SCRIPT_SRC = "https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js";

// Redoc theme presets. Light uses brand orange on white; dark pulls the
// VitePress dark palette (#1b1b1f body / #202127 surface / #e0e0e0 text) so
// the reference visually belongs to the dark docs chrome instead of the
// default eye-bleach-white rectangle.
const LIGHT_THEME = {
  colors: {
    primary: { main: "#e8a020" },
  },
};

const DARK_THEME = {
  colors: {
    primary: { main: "#f5a623" },
    text: { primary: "#e0e0e0", secondary: "#a8a8b3" },
    border: { dark: "#2f2f36", light: "#2f2f36" },
    http: {
      get: "#60a5fa",
      post: "#4ade80",
      put: "#facc15",
      delete: "#f87171",
      options: "#c084fc",
      patch: "#fb923c",
      basic: "#a8a8b3",
      link: "#60a5fa",
      head: "#a8a8b3",
    },
  },
  sidebar: {
    backgroundColor: "#202127",
    textColor: "#e0e0e0",
  },
  rightPanel: {
    backgroundColor: "#0f0f17",
    textColor: "#e0e0e0",
  },
  typography: {
    fontFamily: "system-ui, -apple-system, sans-serif",
    code: {
      color: "#f5a623",
      backgroundColor: "rgba(245, 166, 35, 0.1)",
    },
  },
};

function isDark() {
  return document.documentElement.classList.contains("dark");
}

function mountRedoc() {
  const container = document.getElementById(CONTAINER_ID);
  if (!window.Redoc || !container) return;
  // Redoc doesn't expose unmount — clear the target and re-init so a theme
  // flip renders a fully rebuilt tree instead of stacking on top of the
  // previous one.
  container.innerHTML = "";
  container.style.backgroundColor = isDark() ? "#1b1b1f" : "transparent";
  window.Redoc.init(
    "/docs/openapi.json",
    { theme: isDark() ? DARK_THEME : LIGHT_THEME },
    container,
  );
}

let observer = null;

onMounted(() => {
  function startObserving() {
    mountRedoc();
    // Watch <html> for `.dark` toggling and re-init Redoc when it flips.
    observer = new MutationObserver(() => mountRedoc());
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }

  if (window.Redoc) {
    startObserving();
    return;
  }
  const existing = document.getElementById(SCRIPT_ID);
  if (existing) {
    existing.addEventListener("load", startObserving, { once: true });
    return;
  }
  const script = document.createElement("script");
  script.id = SCRIPT_ID;
  script.src = SCRIPT_SRC;
  script.addEventListener("load", startObserving, { once: true });
  document.body.appendChild(script);
});

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect();
    observer = null;
  }
});
</script>

<style>
/*
  Dark-mode overrides for Redoc controls that the public theme API doesn't
  expose — response-code tabs (200 / 400 / 401 …), request-sample language
  tabs, and the content-type dropdown. Redoc's built-in styles render these
  with a near-white background that punches through the dark chrome; these
  rules scope the fix to our container + .dark class so light mode is
  untouched.
*/
.dark #redoc-container [role="tab"],
.dark #redoc-container [role="tablist"] button,
.dark #redoc-container select,
.dark #redoc-container label[role="button"] {
  background-color: #2a2a33 !important;
  color: rgba(255, 255, 255, 0.92) !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
}

.dark #redoc-container [role="tab"][aria-selected="true"],
.dark #redoc-container [role="tablist"] button.tab-success,
.dark #redoc-container [role="tablist"] button.tab-error,
.dark #redoc-container [role="tablist"] button.tab-redirect {
  background-color: #3a3a44 !important;
  border-color: #f5a623 !important;
}

/* Redoc's status-code pills (Responses list) use hard-coded pastel fills
   that wash out on dark. Tint the backgrounds down to match the page. */
.dark #redoc-container [data-section-id^="operation"] h3 ~ div [class*="ResponseTitle"],
.dark #redoc-container [class*="ResponseTitleWrap"] {
  background-color: transparent !important;
}
</style>

# API reference

Every endpoint the Hive management API exposes, auto-generated from the deployed FastAPI app. Use it alongside the [MCP tools reference](/tools/overview) if you're building SDKs or bots against the REST surface.

<div id="redoc-container"></div>
