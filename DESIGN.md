---
version: alpha
colors:
  primary: '#3155C6'
  background: '#F4F6FB'
  surface: '#FFFFFF'
  ink: '#202B45'
  muted: '#52617B'
  border: '#DCE2EE'
  success: '#276746'
  warning: '#876016'
  danger: '#A22A42'
typography:
  display:
    fontFamily: 'Avenir Next, Trebuchet MS, sans-serif'
  body:
    fontFamily: 'system-ui, -apple-system, sans-serif'
  utility:
    fontFamily: 'SFMono-Regular, Consolas, monospace'
rounded:
  control: '8px'
  panel: '12px'
spacing:
  small: '8px'
  medium: '16px'
  large: '24px'
components:
  primary-action:
    backgroundColor: '#3155C6'
    textColor: '#FFFFFF'
  body:
    textColor: '{colors.ink}'
  caption:
    textColor: '{colors.muted}'
  divider:
    backgroundColor: '{colors.border}'
  success:
    textColor: '{colors.success}'
  warning:
    textColor: '{colors.warning}'
  error:
    textColor: '{colors.danger}'
---
# MemeBot design

## Overview
A compact edit suite for one curator on a Mac. The signature is an episode rundown: a visible ordered list of clips beside the video preview, with durations and review state. Quiet blue-gray surfaces keep colorful source footage dominant. No landing-page hero, dashboard filler, or decorative metrics.

## Colors
DESIGN.md owns tokens. `scripts/sync_theme.py` generates `src/memebot/data/theme.json` and `.streamlit/config.toml`. `ui_components.py` adapts theme.json into shared CSS and Streamlit controls. Never hand-edit generated tokens. Primary blue identifies the next action; errors and warnings always carry text.

## Typography
Avenir Next / Trebuchet headings recall a production slate. System body fonts avoid network downloads; monospace is reserved for timestamps and clip numbers. English interface, America/New_York episode dates.

## Layout
Sidebar: Daily desk, Sources, Clip library, Episodes, Settings. Pages use natural scrolling, a maximum content width of 1280px, and 24px section spacing. Two-column review becomes one column below 1100px, accounting for the sidebar. Headings reduce below 760px. Data tables have bounded heights; longer libraries paginate in batches of 12.

## Elevation & Depth
Flat white panels with subtle borders; no permanent shadows or gradients. Media frames have a neutral dark surround only where footage needs it.

## Shapes
Eight-pixel control corners and twelve-pixel grouped panels. No pills for dense editorial rows.

## Components
Streamlit owns buttons, forms, labeled inputs, authored selectbox/date controls, dialogs, progress, alerts, and keyboard behavior. `ui_components.py` owns shared page headers, actions, feedback, CSS, and job status. Up/down buttons provide a keyboard-accessible alternative to drag ordering. Forms preserve unsaved values in the current session until submitted. Explicit Save actions persist changes; a persistent form caption reminds users to save before navigating.

## Do's and Don'ts
Show useful empty states and actionable failures. Use actual source footage, not decorative art. Show dates with timezone context. Distinguish recorded upload evidence from unknown evidence. Never describe a source as daily without checked history. Keep public Publish separate from private upload. Reduce all motion when requested. Scrollbars remain visible, with a shared global baseline.
