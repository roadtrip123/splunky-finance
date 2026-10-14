import { test, expect } from "@playwright/test";
async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Account number", { exact: true }).fill("12345678");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-customer-password-only");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/banking$/);
}
test("customer banking journey with real offline tool execution", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Your money/ })).toBeVisible();
  await page.goto("/banking");
  await expect(page).toHaveURL(/login$/);
  await login(page);
  await expect(
    page.getByRole("heading", { name: "Hello, Alex." }),
  ).toBeVisible();
  await page.getByRole("link", { name: /Everyday.*1042/ }).click();
  await expect(
    page.getByRole("heading", { name: "Transaction history" }),
  ).toBeVisible();
  await page
    .getByLabel("Category", { exact: true })
    .selectOption("restaurants");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await expect(page.locator("tbody")).toContainText("restaurants");
  await page.getByRole("button", { name: "Open My Bank Agent" }).click();
  await page
    .getByRole("button", {
      name: "How much did I spend on restaurants last month?",
    })
    .click();
  await expect(page.locator(".message.assistant")).toContainText(
    "Restaurant spending was",
  );
  await page.getByRole("button", { name: "Close My Bank Agent" }).click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/login$/);
});
test("presenter controls apply directly without customer login", async ({ page }) => {
  await page.goto("/demo-admin");
  await page.getByLabel("Password", { exact: true }).fill("test-presenter-password-only");
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("button", { name: "Enable Incomplete Answer", exact: true }).click();
  await expect(page.getByRole("button", { name: "Enable Incomplete Answer", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByRole("button", { name: "Enable Incomplete Answer", exact: true })).toHaveAttribute("aria-pressed", "true");
  // One Run button per offered question, so the row is the selector. The first row is the
  // scenario's own question in both scenarios this test walks through.
  const runFirstQuestion = page.locator(".scenario-question").first().getByRole("button", { name: "Run", exact: true });
  await runFirstQuestion.click();
  await expect(page.locator(".demo-response").last()).toContainText("Your spending is recorded.");
  await expect(page.locator(".demo-response").last()).toContainText("Scenario used: Incomplete Answer");
  await page.getByRole("button", { name: "Enable Guardrail Cross-Customer Access", exact: true }).click();
  // Selecting the scenario arms the guardrail, so the transfer is gated before the tool runs.
  await expect(page.getByText("Guardrail armed")).toBeVisible();
  await runFirstQuestion.click();
  // The gate's own fallback, which is what a blocked request delivers. The first gated
  // question is a balance read rather than a transfer: both are blocked by the same control.
  await expect(page.locator(".demo-response").last()).toContainText(
    "That request is not available from My Bank Agent.",
  );
  await expect(page.locator(".demo-response").first()).toContainText("Scenario used: Incomplete Answer");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
test("layout has no horizontal overflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("body")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});

test("presenter can enable and disable Galileo with honest missing-key status", async ({
  page,
}) => {
  await page.goto("/demo-admin");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-presenter-password-only");
  await page.getByRole("button", { name: "Log in" }).click();
  // Labelled with the active backend. The switch is saved across restarts and the browser-test
  // data directory survives between runs, so the starting position is whatever the last run left.
  const enable = page.getByRole("button", {
    name: "Enable Galileo",
    exact: true,
  });
  const disable = page.getByRole("button", {
    name: "Disable Galileo",
    exact: true,
  });
  // isVisible() does not retry. Read it only once one of the two is on the page, or a status
  // fetch still in flight looks like "already disabled" and the next assertion fails.
  await expect(enable.or(disable)).toBeVisible();
  if (await disable.isVisible()) await disable.click();
  await expect(enable).toBeVisible();
  await enable.click();
  await expect(disable).toBeVisible();
  await expect(
    page.getByText("Galileo credentials missing", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(disable).toBeVisible();
  await disable.click();
  await expect(enable).toBeVisible();
});

async function presenter(page: import("@playwright/test").Page) {
  await page.goto('/demo-admin');
  await page.getByLabel('Password', { exact: true }).fill('test-presenter-password-only');
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.getByRole('button', { name: 'Enable Incomplete Answer', exact: true })).toBeVisible();
}
const completePrompt = 'How much did I spend on restaurants last month, what were my three biggest transactions, and how does that compare with the previous month?';
async function verifyLiveSwitch(admin: import("@playwright/test").Page, bank: import("@playwright/test").Page) {
  const footer = bank.locator('.demo-footer');
  await expect(footer).toHaveText('Fictional banking data only');
  await expect(footer).toHaveClass(/demo-footer-normal/);
  await admin.getByRole('button', { name: 'Enable Incomplete Answer', exact: true }).click();
  await expect(footer).toHaveClass(/demo-footer-fault/);
  await expect(admin.getByTestId('banking-link')).toHaveText('connected');
  await bank.getByLabel('Ask My Bank Agent', { exact: true }).fill(completePrompt);
  await bank.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(bank.locator('.message.assistant').last()).toContainText('Your spending is recorded.');
  await admin.getByRole('button', { name: 'Normal Answer / Disabled Guardrails', exact: true }).click();
  await expect(footer).toHaveClass(/demo-footer-normal/);
  await bank.getByLabel('Ask My Bank Agent', { exact: true }).fill(completePrompt);
  await bank.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(bank.locator('.message.assistant')).toHaveCount(2);
  await expect(bank.locator('.message.assistant').last()).toContainText('Restaurant spending was');
  await expect(footer).toHaveText('Fictional banking data only');
}
test('same-browser banking chat follows presenter without refresh', async ({ page, context }) => {
  await login(page);
  await page.getByRole('button', { name: 'Open My Bank Agent' }).click();
  const admin = await context.newPage();
  await presenter(admin);
  await verifyLiveSwitch(admin, page);
  await page.route('**/api/chat/demo-sync', route => route.abort());
  await expect(page.locator('.demo-footer')).toHaveClass(/demo-footer-pending/);
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeDisabled();
  await page.unroute('**/api/chat/demo-sync');
  await expect(page.locator('.demo-footer')).toHaveClass(/demo-footer-normal/);
});
test('another computer pairs once and receives live scenario changes', async ({ page, browser, baseURL }) => {
  await presenter(page);
  await page.getByRole('button', { name: 'Connect using pairing code' }).click();
  const code = await page.getByTestId('pairing-code').innerText();
  const remote = await browser.newContext({ baseURL });
  try {
    const bank = await remote.newPage();
    await login(bank);
    await bank.getByRole('button', { name: 'Open My Bank Agent' }).click();
    await bank.getByText('Demo connection', { exact: true }).click();
    await bank.getByLabel('Pairing code', { exact: true }).fill(code);
    await bank.getByRole('button', { name: 'Connect demo', exact: true }).click();
    await expect(page.getByTestId('banking-link')).toHaveText('connected');
    await bank.getByText('Demo connection', { exact: true }).click();
    await verifyLiveSwitch(page, bank);
    await page.getByRole('button', { name: 'Disconnect banking session' }).click();
    await expect(page.getByRole('button', { name: 'Connect using pairing code' })).toBeVisible();
    await page.getByRole('button', { name: 'Enable Incomplete Answer', exact: true }).click();
    await expect(bank.locator('.demo-footer')).toHaveClass(/demo-footer-normal/);
  } finally { await remote.close(); }
});

test('opening suggestions include the multi-part spending question and faults accept free questions', async ({ page, context }) => {
  await login(page);
  await page.getByRole('button', { name: 'Open My Bank Agent' }).click();
  // The multi-part question is what the Incomplete Answer fault visibly truncates, so it has
  // to be one click away. `completePrompt` is longer still and is typed, not offered.
  await expect(
    page.getByRole('button', {
      name: 'How much did I spend on restaurants last month and what was the largest purchase?',
      exact: false,
    }),
  ).toBeVisible();
  const admin = await context.newPage();
  await presenter(admin);
  // The three answer faults. Named once: the loop and the message count read from the same list.
  const faults = ['Incomplete Answer', 'Incorrect Total', 'Wrong Customer'];
  for (const [index, scenario] of faults.entries()) {
    await admin.getByRole('button', { name: `Enable ${scenario}`, exact: true }).click();
    await expect(admin.getByTestId('banking-link')).toHaveText('connected');
    await page.getByLabel('Ask My Bank Agent', { exact: true }).fill('What is my savings balance?');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect(page.locator('.message.assistant')).toHaveCount(index + 1);
    await expect(page.locator('.message.assistant').last()).not.toContainText('$754.19');
    // The error banner itself, not role=alert: Next's route announcer is an alert and holds
    // the page heading, so it is always present after a client navigation.
    await expect(page.locator('p.error')).toHaveCount(0);
  }
});
