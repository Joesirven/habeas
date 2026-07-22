# module: design-taste

> Gate: any UI or visual design work in `clients/web/`.

**System:** shadcn/ui + Tailwind. Habeas brand accents only. No Amigo frost, no editorial serif heroes, no glass gradients.

## Brand (locked)

| Role | Token / hex | Use |
|------|-------------|-----|
| Primary | `#1E4191` (`habeas-navy`) | Active nav, primary buttons, key links |
| Accent | `#2B7BB9` (`habeas-mid`) | Focus rings, secondary links |
| Soft | `#428BCA` (`habeas-light`) | Soft fills, charts |
| Canvas | `#F8FAFC` | Page background |
| Surface | `#FFFFFF` | Cards, tables, dialogs |
| Border | `#E2E8F0` | Hairlines, inputs |
| Ink | `#0F172A` | Body text |
| Muted | `#64748B` | Labels, secondary |

## Core directive

**Dense, calm ops console.** Prefer shadcn primitives (`Button`, `Badge`, `Tabs`, `Dialog`/`Sheet`, `Table`, `Input`, `Select`) over custom `taste-*` chrome. One job per view. Tables and filters first.

## Visual grammar

1. Sticky header: white/95 + thin border — no backdrop frost gradients.
2. Page chrome: small muted label → `text-xl` title → optional one-line support.
3. Primary zone = table, inbox list, or stage rail — not KPI marketing grids.
4. Status via `Badge` variants (ok / fail / run / wait).
5. Filters = URL search params + compact controls in a bordered toolbar.
6. Side drawer (`Dialog` right sheet) for request triage — History + Matching tabs.
7. Radius: `md` (6–8px). Shadows: one soft level max, or none.
8. Typography: system / Inter-style sans only (`font-body`). Display serif optional for brand wordmark only.

## Do

- Use Habeas navy for primary actions and active states.
- Keep density high on Requests / Inbox / Workers / Runs.
- Fail soft: empty states and API errors never crash the page.

## Don’t

- Purple gradients, cream-luxury editorial, terracotta accents.
- Frosted glass overlays, warm-gray glass chips, multi-layer shadows.
- Large serif heroes, stage-pill marketing rails, bubbly tab buttons.
- Emulate Prefect dark theme or Dagster purple skin.
