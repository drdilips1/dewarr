# Shared controls

Discover's compact controls are the default throughout the app. `apps/web/src/controls.css` owns their visual styling: 30px frames, pill borders, 11px action labels, circular icon buttons, and matching native selects and split-button menus. Inputs align with selects. Primary actions use a subtle accent treatment; pressed, disabled, keyboard-focus, and destructive states remain distinct.

`apps/web/src/app.css` imports all page styles into the `app` cascade layer and shared controls into the subsequent `controls` layer. Import this stylesheet once from `main.tsx`; do not import page styles from lazy components. This prevents navigation order from changing control appearance.

Use native `button` and `select` elements. Buttons receive the default automatically. Add `primary` for the main action, `danger` for destructive actions, and `control-icon` for icon-only buttons (with an accessible name). Links that act as navigation buttons use `control-action`, with `control-icon` when needed. Existing shelf/reader/icon class aliases remain supported. Text links, navigation tabs, book covers, and drag handles retain their distinct roles.

Page styles should control placement and wrapping rather than restating button sizes, colors, or corner radii. Add new shared variants in `controls.css` instead of page overrides. Adjust the `--control-*` tokens there to change the app-wide standard.
