import { defineConfig } from "vitepress";

export default defineConfig({
  base: "/docs/",
  title: "Hive Docs",
  description: "Shared persistent memory for AI agents — documentation",
  cleanUrls: true,
  head: [["link", { rel: "icon", type: "image/svg+xml", href: "/docs/favicon.svg" }]],

  themeConfig: {
    logo: { src: "/logo.svg", alt: "Hive" },
    siteTitle: "Hive",
    nav: [
      { text: "Home", link: "/" },
      { text: "Docs", link: "/" },
      { text: "Sign in", link: "/app" },
    ],

    sidebar: [
      {
        text: "Getting started",
        items: [
          { text: "What is Hive?", link: "/getting-started/what-is-hive" },
          { text: "Quick start", link: "/getting-started/quick-start" },
          { text: "Connect your MCP client", link: "/getting-started/connect-client" },
          { text: "Your first memory", link: "/getting-started/first-memory" },
        ],
      },
      {
        text: "MCP tools reference",
        items: [
          { text: "Overview", link: "/tools/overview" },
          { text: "remember", link: "/tools/remember" },
          { text: "recall", link: "/tools/recall" },
          { text: "forget", link: "/tools/forget" },
          { text: "list_memories", link: "/tools/list-memories" },
          { text: "search_memories", link: "/tools/search-memories" },
          { text: "summarize_context", link: "/tools/summarize-context" },
        ],
      },
      {
        text: "Management UI",
        items: [
          { text: "Memory Browser", link: "/ui-guide/memory-browser" },
          { text: "OAuth clients", link: "/ui-guide/oauth-clients" },
          { text: "Activity log", link: "/ui-guide/activity-log" },
        ],
      },
      {
        text: "Concepts",
        items: [
          { text: "How memory scoping works", link: "/concepts/memory-scoping" },
          { text: "Tags and organisation", link: "/concepts/tags" },
        ],
      },
      {
        text: "FAQ",
        link: "/faq",
      },
    ],

    socialLinks: [{ icon: "github", link: "https://github.com/warlordofmars/hive" }],

    footer: {
      message: "Hive — shared persistent memory for AI agents",
    },

    search: {
      provider: "local",
    },
  },
});
