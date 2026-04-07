import { h } from "vue";
import DefaultTheme from "vitepress/theme";
import "./style.css";

export default {
  ...DefaultTheme,

  // Inject a plain <a href="/app"> Sign in button via layout slots so it is
  // never handled by Vue Router.  A RouterLink for /app would push /docs/app
  // onto the browser history stack (VitePress base prepend), causing a 404
  // when the user presses Back from /app.  A vanilla <a> bypasses all of that.
  Layout() {
    return h(DefaultTheme.Layout, null, {
      // Desktop navbar — appears between nav links and search/social icons
      "nav-bar-content-before": () =>
        h("a", { href: "/app", class: "docs-signin-btn" }, "Sign in"),
      // Mobile expanded menu — appears at the bottom of the nav screen
      "nav-screen-content-after": () =>
        h("a", { href: "/app", class: "docs-signin-screen-btn" }, "Sign in"),
    });
  },

  enhanceApp() {
    // Vue Router 4 intercepts ALL same-origin anchor clicks, including hrefs
    // that are outside its /docs/ base (e.g. "/" for marketing, "/app" for
    // Sign in). Intercept these in the capture phase so we fire before Vue
    // Router and force a real full-page navigation with window.location.href.
    if (typeof window !== "undefined") {
      document.addEventListener(
        "click",
        (e) => {
          // Logo → marketing page root
          const title = e.target.closest(".VPNavBarTitle .title");
          if (title && title.getAttribute("href") === "/") {
            e.preventDefault();
            e.stopImmediatePropagation();
            window.location.href = "/";
            return;
          }
          // Sign in button → /app (injected via layout slot as plain <a>)
          const signin = e.target.closest(".docs-signin-btn, .docs-signin-screen-btn");
          if (signin) {
            e.preventDefault();
            e.stopImmediatePropagation();
            window.location.href = "/app";
          }
        },
        true, // capture phase — fires before Vue Router's link handler
      );
    }
  },
};
