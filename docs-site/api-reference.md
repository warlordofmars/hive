---
title: API reference
outline: deep
pageClass: api-reference-page
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
  sidebar: {
    backgroundColor: "#f8f8fa",
    textColor: "#1f1f23",
  },
  // Redoc's default right panel is dark-grey (#263238) even in light mode —
  // the "classic" three-pane look. That clashes with the rest of the light
  // docs chrome, so override to a soft light surface. Code blocks inside
  // keep their own darker background via codeBlock.backgroundColor below.
  rightPanel: {
    backgroundColor: "#f0f0f3",
    textColor: "#1f1f23",
  },
  codeBlock: {
    backgroundColor: "#2a2a33",
  },
  typography: {
    code: {
      color: "#b8560f",
      backgroundColor: "rgba(232, 160, 32, 0.1)",
    },
  },
};

const DARK_THEME = {
  colors: {
    primary: { main: "#f5a623" },
    text: {
      primary: "rgba(255, 255, 255, 0.92)",
      secondary: "rgba(255, 255, 255, 0.62)",
    },
    border: {
      dark: "rgba(255, 255, 255, 0.14)",
      light: "rgba(255, 255, 255, 0.08)",
    },
    http: {
      get: "#60a5fa",
      post: "#4ade80",
      put: "#facc15",
      delete: "#f87171",
      options: "#c084fc",
      patch: "#fb923c",
      basic: "rgba(255, 255, 255, 0.62)",
      link: "#60a5fa",
      head: "rgba(255, 255, 255, 0.62)",
    },
    // Status-code blocks on each endpoint. Redoc's defaults are dark saturated
    // colours on 6–10% tints — readable on white, nearly invisible on dark.
    // Use brighter Tailwind-300-tier colours so the text pops off the low-alpha
    // fill in dark mode.
    responses: {
      success: {
        color: "#4ade80",
        backgroundColor: "rgba(74, 222, 128, 0.12)",
        tabTextColor: "#4ade80",
      },
      error: {
        color: "#f87171",
        backgroundColor: "rgba(248, 113, 113, 0.12)",
        tabTextColor: "#f87171",
      },
      redirect: {
        color: "#fbbf24",
        backgroundColor: "rgba(251, 191, 36, 0.12)",
        tabTextColor: "#fbbf24",
      },
      info: {
        color: "#60a5fa",
        backgroundColor: "rgba(96, 165, 250, 0.12)",
        tabTextColor: "#60a5fa",
      },
    },
  },
  sidebar: {
    backgroundColor: "#1a1a23",
    textColor: "rgba(255, 255, 255, 0.92)",
  },
  rightPanel: {
    backgroundColor: "#2a2a33",
    textColor: "rgba(255, 255, 255, 0.92)",
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

/*
  Layout: VitePress's default doc layout caps .VPDoc .container at 1152px
  and reserves part of that for an outline aside. Redoc's three-pane layout
  needs the full remaining width (after the left sidebar) — otherwise
  "Content application/json" wraps mid-phrase and the right-panel code
  samples become an unreadable sliver. Scope the overrides to the
  api-reference page only so every other doc keeps its standard width.
*/
.api-reference-page .VPDoc {
  padding: 0 !important;
}

.api-reference-page .VPDoc .container,
.api-reference-page .VPDoc .content,
.api-reference-page .VPDoc .content-container {
  max-width: none !important;
  padding: 0 !important;
  margin: 0 !important;
}

/* Hide the right-side table-of-contents aside — Redoc has its own sidebar
   navigation, so the VP outline is both redundant and steals width. */
.api-reference-page .VPDocAside,
.api-reference-page .VPDoc.has-aside .content-container {
  display: block !important;
}

.api-reference-page .VPDocAsideOutline,
.api-reference-page .aside {
  display: none !important;
}

/* Give the intro H1 + paragraph some breathing room, then let Redoc span
   the full width beneath. */
.api-reference-page main > h1,
.api-reference-page main > p {
  padding: 24px 24px 0;
  margin: 0;
}

.api-reference-page main > p {
  padding-bottom: 16px;
}

.api-reference-page #redoc-container {
  width: 100%;
}
</style>

# API reference

Every endpoint the Hive management API exposes, auto-generated from the deployed FastAPI app. Use it alongside the [MCP tools reference](/tools/overview) if you're building SDKs or bots against the REST surface.

<div id="redoc-container"></div>
