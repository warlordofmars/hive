# Changelog

All notable changes to Hive are documented here. Releases correspond to GitHub tags and follow [semantic versioning](https://semver.org/).

See the [GitHub releases page](https://github.com/warlordofmars/hive/releases) for full release notes generated from merged PRs.

## v0.16.1 — 2026-04-09

### Fixed

- Upgrade `cryptography` 46.0.6 → 46.0.7 to address CVE-2026-39892 (#237)

## v0.16.0 — 2026-04-08

### Added

- Marketing site expanded with Pricing, FAQ, Use Cases, MCP Client Compatibility, Changelog, and Status pages (#231, #232, #234)
- Shared `PageLayout` component with consistent header/footer nav across all marketing pages (#231)
- `ChangelogPage` parses `CHANGELOG.md` at build time and renders versioned sections with color-coded change groups (#234)
- `StatusPage` performs a live health check against `GET /health` with refresh and checked-at time display (#234)
- shadcn/ui component foundation with Tailwind v4 design tokens matching VitePress docs site branding (#228)

### Fixed

- Tailwind utility classes (`mx-auto`) overridden by unlayered CSS reset — moved reset into `@layer base` (#229)
- Flash of light background on dark-mode page load — synchronous inline theme script applied before first paint (#230)
- E2e mobile menu toggle test replaced fixed 300ms wait with condition-based `wait_for` (#235)

## v0.15.0 — 2026-04-07

### Added

- VitePress user-facing documentation site hosted at `/docs` (#201)
- CloudFront routing for `/docs/*` with clean URL rewriting — VitePress `cleanUrls` output served correctly without trailing-slash issues (#201, #204, #205)
- Docs site themed to match marketing site: dark navy navbar, orange accent, Hive logo/favicon (#203, #207, #220)
- Docs navbar with Docs and Sign in links rendered as plain `<a>` elements (bypasses Vue Router so navigation works correctly across site boundaries) (#209, #210, #213, #214, #221, #222)
- `/docs` and `/docs/` redirect to `what-is-hive` first doc page (#215)
- Playwright e2e test suite for docs site: routing, navbar appearance, nav link clicks, logo/Sign in navigation, mobile hamburger (#204, #209, #210, #211, #213, #214, #221, #222)

### Fixed

- Dark mode toggle and GitHub icon removed from docs navbar (#223, #224)
- Logo navigates to marketing page root (Vue Router SPA interception bypassed) (#213)
- Sign in button positioned at far right of navbar next to Docs link (#222)

## v0.14.0 — 2026-04-06

### Added

- Semantic memory search via Amazon S3 Vectors + Bedrock Titan Embeddings V2 — new `search_memories` MCP tool and `GET /api/memories?search=` API endpoint return memories ranked by cosine similarity (#193, #194)
- Debounced semantic search input in Memory Browser UI with match score badges (#193, #194)

### Fixed

- SetupPanel tab and JSON panel colors were hardcoded light-mode values and did not render correctly in dark mode (#196)

## v0.13.1 — 2026-04-06

### Fixed

- LoginPage tagline still referenced "Claude agents" after #184 — updated to "AI agents" (#188)

## v0.13.0 — 2026-04-06

### Added

- Scheduled synthetic traffic workflow generating real CloudWatch metrics every 15 minutes (#154)
- E2E tests for CloudWatch metrics dashboard, including admin API and UI validation (#157)
- Dark mode support with OS preference detection and manual toggle; CSS design tokens via Tailwind v4 (#175)
- Visual identity — logo, favicon, and social preview image (#173)
- Make Google auth bypass conditional on `test_email` param for safer e2e testing (#170, #171)

### Fixed

- MCP client setup instructions for Claude Desktop and Claude Code (#169)
- Marketing page layout: logo, wordmark, 2×2 feature grid, consistent 1100px content width (#178–#181)
- Dark mode applied to all routes (LoginPage, HomePage) via `useTheme` at App root (#182, #183)

### Changed

- Broadened messaging from Claude-specific to MCP-compatible; added Cursor and Continue setup docs and onboarding snippets (#184)

## Earlier releases

See [GitHub releases](https://github.com/warlordofmars/hive/releases) for the full history.
