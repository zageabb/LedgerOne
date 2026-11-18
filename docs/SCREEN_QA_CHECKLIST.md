# LedgerOne screen QA checklist

Use for each new or materially changed browser screen. Record PASS / FAIL / N/A with evidence; a checklist alone does not prove implementation.

## Identity and visual behaviour
- [ ] Screen ID, purpose, route, UI mode (Home/Apprentice or Professional), owner and permissions documented.
- [ ] Existing app header/navigation, field, button, table, dialogue and feedback patterns reused.
- [ ] Colours, type, spacing and status cues use known project tokens; light/dark variants tested where implemented.
- [ ] Layout works at 1440, 1280, 1024, 768 and 390 CSS px and 200% zoom, or deviations recorded.
- [ ] No clipped controls or inaccessible overflow; financial amounts right-aligned with explicit currency/precision.

## Data and accounting semantics
- [ ] Loading, empty, unknown, failed, stale, unauthorised and optional not_configured states are distinct.
- [ ] Monetary signs, balances, totals, period/date context, rounding and currencies are explained.
- [ ] Draft/posted/void/reversed/paid/partially settled statuses remain unambiguous and accessible.
- [ ] Validation, dirty/unsaved state, write permissions and confirmation for consequential postings covered.
- [ ] Error messages do not leak tokens, account secrets or cross-organisation data.

## Accessibility and security
- [ ] Keyboard navigation, visible focus, labels, errors, screen reader names and contrast reviewed against WCAG 2.2 AA target.
- [ ] Status is never expressed by colour alone; touch targets and zoom usability checked.
- [ ] CSRF, session context, role checks, audit events and organisation isolation tested where relevant.

## Delivery evidence
- [ ] Relevant unit/API/browser tests and exact result recorded.
- [ ] Direct root and UDA `/apps/ledgerone/` routes checked where impacted.
- [ ] User manual updated in the same change or no-impact rationale recorded.
- [ ] PR, commit, CI, deployment check, screenshot and user/business acceptance tracked separately.

Reference: [Application-Standard screen QA](https://github.com/zageabb/Application-Standard/blob/main/docs/SCREEN_QA_CHECKLIST.md).
