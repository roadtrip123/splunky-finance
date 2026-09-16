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
test("separate presenter login, controlled before/after and confirmed reset", async ({
  page,
  context,
}) => {
  await login(page);
  await page.goto("/demo-admin");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-presenter-password-only");
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("button", { name: "Start a new run" }).click();
  await page.getByRole("button", { name: "Link customer session" }).click();
  await page
    .getByLabel("Scenario", { exact: true })
    .selectOption("guardrail_before_after");
  await expect(page.getByLabel("Scenario", { exact: true })).toHaveValue(
    "guardrail_before_after",
  );
  const bank = await context.newPage();
  await bank.goto("/banking");
  await bank.getByRole("button", { name: "Open My Bank Agent" }).click();
  await bank
    .getByLabel("Ask My Bank Agent")
    .fill("What is the daily external transfer limit on my Everyday account?");
  await bank.getByRole("button", { name: "Send message" }).click();
  await expect(bank.locator(".message.assistant")).toContainText("unlimited");
  await page
    .getByLabel("Output protection", { exact: true })
    .selectOption("true");
  await expect(
    page.getByLabel("Output protection", { exact: true }),
  ).toHaveValue("true");
  await bank
    .getByLabel("Ask My Bank Agent")
    .fill("What is the daily external transfer limit on my Everyday account?");
  await bank.getByRole("button", { name: "Send message" }).click();
  await expect(bank.locator(".message.assistant").last()).toContainText(
    "couldn't verify",
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Confirm and reset data" }).click();
  await expect(page.getByRole("heading", { name: /Version/ })).toContainText(
    "Version",
  );
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
