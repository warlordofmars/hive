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
      // Desktop navbar — appears after social/search icons on the right
      "nav-bar-content-after": () =>
        h("a", { href: "/app", class: "docs-signin-btn" }, "Sign in"),
      // Mobile expanded menu — appears at the bottom of the nav screen
      "nav-screen-content-after": () =>
        h("a", { href: "/app", class: "docs-signin-screen-btn" }, "Sign in"),
    });
  },

  enhanceApp() {
    // VitePress's Vue Router intercepts root-relative link clicks, including
    // the logo which points to "/" (marketing root).  Intercept in the capture
    // phase so we fire before Vue Router and force a real full-page navigation.
    if (typeof window !== "undefined") {
      document.addEventListener(
        "click",
        (e) => {
          const title = e.target.closest(".VPNavBarTitle .title");
          if (title && title.getAttribute("href") === "/") {
            e.preventDefault();
            e.stopImmediatePropagation();
            window.location.href = "/";
          }
        },
        true, // capture phase — fires before Vue Router's link handler
      );
    }
  },
};
