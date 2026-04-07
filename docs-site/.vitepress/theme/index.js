import DefaultTheme from "vitepress/theme";
import "./style.css";

export default {
  ...DefaultTheme,

  enhanceApp({ router }) {
    // VitePress's Vue Router intercepts ALL root-relative link clicks, including
    // the logo link (href="/"). That keeps the user in the VitePress SPA instead
    // of navigating to the marketing page. Intercept the click in the capture
    // phase (before Vue Router) and force a full page navigation for href="/".
    if (typeof window !== "undefined") {
      document.addEventListener(
        "click",
        (e) => {
          const a = e.target.closest(".VPNavBarTitle .title");
          if (a && a.getAttribute("href") === "/") {
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
