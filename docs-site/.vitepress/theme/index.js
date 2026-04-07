import { h } from "vue";
import DefaultTheme from "vitepress/theme";
import "./style.css";

export default {
  ...DefaultTheme,

  // Inject Docs and Sign in as plain <a> elements via nav-bar-content-after so
  // they render at the far right of the navbar (after search/social), in the
  // correct order, without Vue Router involvement.
  //
  // VitePress .content-body flex order:
  //   [nav-bar-content-before] Search Menu Appearance Social [nav-bar-content-after]
  //
  // Using nav-bar-content-after puts our links at the rightmost position, which
  // matches the marketing site layout: ... Docs | Sign in (at right edge).
  Layout() {
    return h(DefaultTheme.Layout, null, {
      "nav-bar-content-after": () =>
        h("div", { class: "docs-nav-group" }, [
          h(
            "a",
            { href: "/docs/getting-started/what-is-hive", class: "docs-nav-link" },
            "Docs",
          ),
          h("a", { href: "/app", class: "docs-signin-btn" }, "Sign in"),
        ]),
      // Mobile expanded menu
      "nav-screen-content-after": () =>
        h("div", { class: "docs-screen-group" }, [
          h(
            "a",
            { href: "/docs/getting-started/what-is-hive", class: "docs-screen-nav-link" },
            "Docs",
          ),
          h("a", { href: "/app", class: "docs-signin-screen-btn" }, "Sign in"),
        ]),
    });
  },

  enhanceApp() {
    // Vue Router 4 intercepts ALL same-origin anchor clicks, even hrefs outside
    // its /docs/ base. Intercept in capture phase and force window.location.href
    // for links that must cause a real full-page navigation.
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
          // Sign in → /app
          const signin = e.target.closest(".docs-signin-btn, .docs-signin-screen-btn");
          if (signin) {
            e.preventDefault();
            e.stopImmediatePropagation();
            window.location.href = "/app";
          }
        },
        true,
      );
    }
  },
};
