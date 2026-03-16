# Default Browser Operation Recipes

Use these recipes when the user asks for a browser workflow but does not specify every click.

## Standard Bootstrap

1. Resize the browser to a desktop viewport such as `1440x900`.
2. Navigate to the target URL.
3. Wait for a stable heading, navbar label, or other visible anchor text.
4. Detect and dismiss common blockers:
   - Cookie banners
   - Region or language selectors
   - Newsletter or app-install modals
   - Chat widgets covering buttons
5. Dismiss only the blockers that prevent the requested task.
6. Save a screenshot if the user wants proof.

## Login Gate

If the page redirects to sign-in:

1. Stop if credentials are not already available from the user session.
2. If the browser is already logged in, continue normally.
3. If MFA or CAPTCHA appears, ask the user to complete it, then resume from the current page.

## Search And Filter

1. Find the primary search box or filter trigger.
2. Add a selector-driven step to the script when search automation is needed repeatedly.
3. Submit with Enter or the visible search button.
4. Wait for result text, result counts, or loading indicators to settle.
5. If filters are needed, apply one filter at a time and verify the change after each step.

## Form Fill

1. Add explicit selectors for each field into the script.
2. Prefer stable selectors such as labels, placeholders, or `data-testid`.
3. Review visible values before submit.
4. Submit only if the user asked to complete the action.

## Extraction And Proof

1. Extract visible text from the page, not assumptions.
2. If the result matters, take a screenshot after the final state loads.
3. Return concise structured output:
   - Final URL
   - Key visible values
   - Whether the task completed
   - Any blocker or uncertainty
