---
name: Clinical Intelligence
colors:
  surface: '#051424'
  surface-dim: '#051424'
  surface-bright: '#2c3a4c'
  surface-container-lowest: '#010f1f'
  surface-container-low: '#0d1c2d'
  surface-container: '#122131'
  surface-container-high: '#1c2b3c'
  surface-container-highest: '#273647'
  on-surface: '#d4e4fa'
  on-surface-variant: '#bcc9cd'
  inverse-surface: '#d4e4fa'
  inverse-on-surface: '#233143'
  outline: '#869397'
  outline-variant: '#3d494c'
  surface-tint: '#4cd7f6'
  primary: '#4cd7f6'
  on-primary: '#003640'
  primary-container: '#06b6d4'
  on-primary-container: '#00424f'
  inverse-primary: '#00687a'
  secondary: '#d0bcff'
  on-secondary: '#3c0091'
  secondary-container: '#571bc1'
  on-secondary-container: '#c4abff'
  tertiary: '#ffb873'
  on-tertiary: '#4b2800'
  tertiary-container: '#e89337'
  on-tertiary-container: '#5b3200'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#acedff'
  primary-fixed-dim: '#4cd7f6'
  on-primary-fixed: '#001f26'
  on-primary-fixed-variant: '#004e5c'
  secondary-fixed: '#e9ddff'
  secondary-fixed-dim: '#d0bcff'
  on-secondary-fixed: '#23005c'
  on-secondary-fixed-variant: '#5516be'
  tertiary-fixed: '#ffdcbf'
  tertiary-fixed-dim: '#ffb873'
  on-tertiary-fixed: '#2d1600'
  on-tertiary-fixed-variant: '#6a3b00'
  background: '#051424'
  on-background: '#d4e4fa'
  surface-variant: '#273647'
typography:
  display-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  title-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '500'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-caps:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 8px
  container-margin-mobile: 16px
  container-margin-desktop: 32px
  gutter: 16px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 32px
---

## Brand & Style

The design system is engineered to project clinical precision through a high-tech lens. It targets medical professionals and patients in the Indian healthcare landscape, prioritizing trust, accessibility, and modern efficiency. 

The aesthetic is a refined **Glassmorphism**, utilizing deep slate backgrounds to reduce eye strain in clinical environments while using vibrant medical teals and soft purples to guide the user's attention. The UI should feel like a premium digital tool—sophisticated enough for a surgeon's dashboard yet intuitive enough for a patient's first interaction. The inclusion of Hindi script support ensures local relevance without sacrificing the "cutting-edge" AI identity.

## Colors

This design system utilizes a "Deep Tech" dark palette optimized for high-contrast legibility. 

- **Primary (Medical Teal):** Used for critical actions, active states, and clinical branding. It symbolizes health and technological precision.
- **Secondary (Soft Purple):** Used for AI-driven features, such as the Vaidya AI chat interface and insights, differentiating human-managed data from machine-generated suggestions.
- **Neutral (Slate):** Various shades of slate provide a hierarchical structure for secondary text and borders.
- **Background:** A constant deep navy (#0F172A) provides the base for glassmorphic layers to sit upon.

## Typography

The typography system balances the friendly, geometric nature of **Plus Jakarta Sans** for headings with the systematic clarity of **Inter** for functional body text.

- **Headlines:** Use Plus Jakarta Sans for all titles and headlines. This font provides the soft, approachable geometric feel necessary for a patient-facing medical app.
- **Body & Hindi:** Inter is the workhorse for all data, descriptions, and Hindi translations. Its neutral character ensures that medical terminology remains the focus.
- **Hindi Legibility:** For Devanagari text, increase the line-height by 10% compared to English counterparts to prevent vowel markings from clashing between lines.

## Layout & Spacing

The design system follows a mobile-first, **fluid grid** approach based on an 8px base unit.

- **Mobile:** A 4-column layout with 16px side margins. Chat interfaces occupy the full width minus margins.
- **Desktop Dashboards:** A 12-column grid. Sidebars for clinic navigation should be fixed at 280px, with the remaining content area being fluid.
- **Spacing Philosophy:** Use generous white space (stack-lg) between distinct patient records or modules to prevent visual clutter in data-heavy medical environments.

## Elevation & Depth

Depth is achieved through **Glassmorphism** rather than traditional drop shadows.

- **Surface Layers:** Surfaces use a semi-transparent background (`rgba(30, 41, 59, 0.7)`) with a `backdrop-filter: blur(12px)`.
- **Borders:** Every card and container must have a 1px solid border with a low opacity (`rgba(255, 255, 255, 0.1)`) to define the edges against the dark background.
- **Active Elevation:** When an element is focused or active, increase the border opacity and add a subtle outer glow using the Primary Teal color (`box-shadow: 0 0 15px rgba(6, 182, 212, 0.2)`).

## Shapes

The shape language is modern and "Soft-Tech." 

- **Cards & Modals:** Use the standard `rounded-lg` (16px) for all main containers to evoke a friendly, non-clinical feel.
- **Input Fields:** Use `rounded-md` (8px) to maintain a sense of structural integrity and precision.
- **Buttons:** Primary action buttons should use `rounded-full` (pill-shaped) to distinguish them clearly from layout containers and cards.

## Components

### Chat Bubbles (WhatsApp Style)
- **Patient Messages:** Aligned left, Slate-800 background, white text.
- **Vaidya AI Messages:** Aligned right, subtle Purple gradient background (`from secondary to primary`), white text.
- **Status Indicators:** "Sent", "Read", and "AI Processing" indicators sit at the bottom right of the bubble.

### Glassmorphic Cards
- Used for dashboard widgets (e.g., "Today's Appointments"). 
- Header within the card should have a subtle bottom divider.
- Content inside cards uses Inter for high-density data.

### Input Fields
- Dark backgrounds (`#1E293B`) with 1px slate borders.
- Floating labels using Plus Jakarta Sans.
- Active state: Border transitions to Primary Teal with a subtle glow.

### Buttons
- **Primary:** Gradient from Primary Teal to a slightly darker cyan. High-contrast white text.
- **Ghost:** Transparent background, Teal border, Teal text. Used for secondary actions like "View History."

### Chips/Badges
- Used for appointment status: `Confirmed` (Teal), `Pending` (Purple), `Cancelled` (Red).
- 12px font size, semi-transparent background with high-opacity text.