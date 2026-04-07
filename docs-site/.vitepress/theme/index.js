import DefaultTheme from "vitepress/theme";
import "./style.css";

export default {
  ...DefaultTheme,

  enhanceApp({ router }) {
    // VitePress's Vue Router intercepts ALL root-relative link clicks, including
    // links that should navigate outside the docs (logo → "/", Sign in → "/app").
    // Intercept those clicks in the capture phase (before Vue Router) and call
    // window.location.href directly to force a real full-page navigation.
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

          // Sign in nav link → /app
          // VitePress base prepends /docs/ making the href /docs/app, which Vue
          // Router would handle as a client-side route. Navigate directly to /app.
          const navLink = e.target.closest(".VPNavBarMenuLink");
          if (navLink && navLink.getAttribute("href") === "/docs/app") {
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
