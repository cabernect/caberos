# Design System Master File — CaberOS

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** CaberOS
**Category:** AI Agent Operating System (conversation-first)
**Generated:** 2026-07-28

---

## Global Rules

### Style

**Style:** AI-Native UI

**Keywords:** Chatbot, conversational, voice, assistant, agentic, ambient, minimal chrome, streaming text, AI interactions

**Best For:** AI products, chatbots, voice assistants, copilots, AI-powered tools, conversational interfaces

**Performance:** Excellent | **Accessibility:** WCAG AA

**Key Effects:** Typing indicators (3-dot pulse), streaming text animations, pulse animations, context cards, smooth reveals

### Color Palette

**v0.1 is dark-only.** Light mode is a future consideration. The palette below is the dark theme — the only theme in v0.1.

| Role | Hex | CSS Variable | Usage |
|------|-----|--------------|-------|
| Primary | `#F8FAFC` | `--color-primary` | Headings, primary text |
| Secondary | `#94A3B8` | `--color-secondary` | Secondary text, muted UI |
| CTA/Accent | `#6366F1` | `--color-cta` | AI accent, active states, focus rings |
| Background | `#0A0A0A` | `--color-background` | Full viewport background |
| Surface | `#171717` | `--color-surface` | Cards, tool call blocks, user message bubbles |
| Surface Hover | `#262626` | `--color-surface-hover` | Hover states |
| Text | `#F8FAFC` | `--color-text` | Body text |
| Border | `#262626` | `--color-border` | Subtle borders |
| Success | `#10B981` | `--color-success` | Approved syscalls, heartbeat ok |
| Warning | `#F59E0B` | `--color-warning` | Pending approvals |
| Danger | `#EF4444` | `--color-danger` | Denied syscalls, errors |
| Heartbeat | `#8B5CF6` | `--color-heartbeat` | Heartbeat-triggered messages |

**Color Notes:** Minimal black + AI purple accent (#6366F1). The accent is used sparingly — for AI identity, active states, and focus rings. Heartbeat messages use a distinct purple to distinguish from user messages.

### Typography

- **Heading Font:** Inter
- **Body Font:** Inter
- **Mono Font:** JetBrains Mono (for shell output, code blocks, tool calls)
- **Mood:** minimal, clean, swiss, functional, neutral, professional
- **Best For:** Dashboards, admin panels, documentation, enterprise apps, design systems

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
```

**Font Scale:**
| Token | Size | Weight | Usage |
|-------|------|--------|-------|
| `--text-xs` | 12px | 400 | Timestamps, metadata |
| `--text-sm` | 14px | 400 | Body small, labels |
| `--text-base` | 16px | 400 | Body, message text |
| `--text-lg` | 18px | 500 | Section headings |
| `--text-xl` | 20px | 600 | Page titles |
| `--text-2xl` | 24px | 700 | Agent name in conversation |

### Spacing Variables

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps, icon-to-text |
| `--space-sm` | `8px` / `0.5rem` | Inline spacing, message padding |
| `--space-md` | `16px` / `1rem` | Standard padding, message gap |
| `--space-lg` | `24px` / `1.5rem` | Section padding, conversation padding |
| `--space-xl` | `32px` / `2rem` | Large gaps, sidebar width padding |
| `--space-2xl` | `48px` / `3rem` | Section margins |

### Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | `6px` | Small elements, badges |
| `--radius-md` | `8px` | Buttons, inputs |
| `--radius-lg` | `12px` | Cards, message bubbles |
| `--radius-full` | `9999px` | Avatars, pills |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, dropdowns |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, popovers |

---

## Component Specs

### Message Bubbles

```css
/* User message — right aligned */
.msg-user {
  background: var(--color-surface);
  color: var(--color-text);
  border-radius: var(--radius-lg);
  padding: var(--space-sm) var(--space-md);
  margin-left: auto;
  max-width: 80%;
}

/* AI message — left aligned, no bubble (ambient) */
.msg-ai {
  color: var(--color-text);
  padding: var(--space-sm) 0;
  max-width: 80%;
}

/* Heartbeat message — left aligned, accent border */
.msg-heartbeat {
  border-left: 3px solid var(--color-heartbeat);
  padding-left: var(--space-md);
  color: var(--color-secondary);
  font-size: var(--text-sm);
}
```

### Tool Call Block (inline, collapsible)

```css
.tool-call {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-sm) var(--space-md);
  font-family: 'JetBrains Mono', monospace;
  font-size: var(--text-sm);
  cursor: pointer;
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.tool-call-status-allowed { color: var(--color-success); }
.tool-call-status-denied { color: var(--color-danger); }
.tool-call-status-pending { color: var(--color-warning); }
```

### Typing Indicator

```css
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: var(--space-sm);
}

.typing-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-secondary);
  animation: typing-pulse 1.4s infinite ease-in-out;
}

.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing-pulse {
  0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
  30% { opacity: 1; transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .typing-dot { animation: none; opacity: 0.5; }
}
```

### Chat Input (sticky bottom)

```css
.chat-input {
  position: sticky;
  bottom: 0;
  background: var(--color-background);
  border-top: 1px solid var(--color-border);
  padding: var(--space-md) var(--space-lg);
}

.chat-input textarea {
  width: 100%;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-sm) var(--space-md);
  font-family: 'Inter', sans-serif;
  font-size: var(--text-base);
  color: var(--color-text);
  resize: none;
  min-height: 48px;
  max-height: 200px;
}

.chat-input textarea:focus {
  border-color: var(--color-cta);
  outline: none;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
}
```

### Agent List Card (landing page)

```css
.agent-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-md) var(--space-lg);
  cursor: pointer;
  transition: all 200ms ease;
}

.agent-card:hover {
  background: var(--color-surface-hover);
  border-color: var(--color-cta);
}

.agent-card-name {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--color-text);
}

.agent-card-meta {
  font-size: var(--text-sm);
  color: var(--color-secondary);
}

.agent-card-heartbeat-badge {
  font-size: var(--text-xs);
  color: var(--color-heartbeat);
  border: 1px solid var(--color-heartbeat);
  border-radius: var(--radius-full);
  padding: 2px 8px;
}
```

---

## Anti-Patterns (Do NOT Use)

- **Heavy chrome** — minimal borders, minimal toolbars. The conversation is the UI.
- **Slow response feedback** — show typing indicator within 300ms. Show streaming tokens as they arrive.
- **Emojis as icons** — use SVG icons (Lucide preferred, matches shadcn/ui)
- **Missing cursor:pointer** — all clickable elements must have cursor:pointer
- **Layout-shifting hovers** — avoid scale transforms that shift layout; use color/opacity transitions
- **Low contrast text** — maintain 4.5:1 minimum contrast ratio
- **Instant state changes** — always use transitions (150-300ms)
- **Invisible focus states** — focus states must be visible for a11y
- **Infinite decorative animations** — animations only for loading/typing indicators

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use Lucide SVG icons via shadcn/ui)
- [ ] All icons from Lucide (consistent with shadcn/ui)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Text contrast 4.5:1 minimum (WCAG AA)
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected (disable typing indicator, streaming animations)
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
- [ ] Dark mode is the default theme
- [ ] Streaming text has a visible cursor or indicator
- [ ] Tool call blocks are collapsible (expand to see full output)
- [ ] Heartbeat messages are visually distinct from user messages
