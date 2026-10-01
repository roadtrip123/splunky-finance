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
  await page.getByRole("button", { name: "Run example question" }).click();
  await expect(page.locator(".demo-response").last()).toContainText("Your spending is recorded.");
  await expect(page.locator(".demo-response").last()).toContainText("Scenario used: Incomplete Answer");
  await page.getByRole("button", { name: "Enable Guardrail Cross-Customer Access", exact: true }).click();
  // Selecting the scenario arms the guardrail, so the transfer is gated before the tool runs.
  await expect(page.getByText("Guardrail armed")).toBeVisible();
  await page.getByRole("button", { name: "Run example question" }).click();
  await expect(page.locator(".demo-response").last()).toContainText(
    "Transfer option is not available",
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
  const enable = page.getByRole("button", {
    name: "Enable Galileo",  // labelled with the active backend
    exact: true,
  });
  const disable = page.getByRole("button", {
    name: "Disable Galileo",
    exact: true,
  });
  if (await disable.isVisible()) await disable.click();
  await expect(enable).toBeVisible();
  await enable.click();
  await expect(disable).toBeVisible();
  await expect(
    page.getByText("Galileo API key missing", { exact: true }),
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
  await expect(admin.getByText('Applied to connected banking session', { exact: true })).toBeVisible();
  await bank.getByLabel('Ask My Bank Agent', { exact: true }).fill(completePrompt);
  await bank.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(bank.locator('.message.assistant').last()).toContainText('Your spending is recorded.');
  await admin.getByRole('button', { name: 'Normal Answers', exact: true }).click();
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
    await expect(page.getByText('Applied to connected banking session', { exact: true })).toBeVisible();
    await bank.getByText('Demo connection', { exact: true }).click();
    await verifyLiveSwitch(page, bank);
    await page.getByRole('button', { name: 'Disconnect banking session' }).click();
    await expect(page.getByRole('button', { name: 'Connect using pairing code' })).toBeVisible();
    await page.getByRole('button', { name: 'Enable Incomplete Answer', exact: true }).click();
    await expect(bank.locator('.demo-footer')).toHaveClass(/demo-footer-normal/);
  } finally { await remote.close(); }
});

test('opening suggestions include the full spending question and faults accept free questions', async ({ page, context }) => {
  await login(page);
  await page.getByRole('button', { name: 'Open My Bank Agent' }).click();
  await expect(page.getByRole('button', { name: completePrompt, exact: false })).toBeVisible();
  const admin = await context.newPage();
  await presenter(admin);
  for (const scenario of ['Incomplete Answer', 'Incorrect Total', 'Hallucinated Policy']) {
    await admin.getByRole('button', { name: `Enable ${scenario}`, exact: true }).click();
    await expect(admin.getByText('Applied to connected banking session', { exact: true })).toBeVisible();
    await page.getByLabel('Ask My Bank Agent', { exact: true }).fill('What is my savings balance?');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    const count = ['Incomplete Answer', 'Incorrect Total', 'Hallucinated Policy'].indexOf(scenario) + 1;
    await expect(page.locator('.message.assistant')).toHaveCount(count);
    await expect(page.locator('.message.assistant').last()).not.toContainText('$754.19');
    await expect(page.getByRole('alert')).toHaveCount(0);
  }
});
