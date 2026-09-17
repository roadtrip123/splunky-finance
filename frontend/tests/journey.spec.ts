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
  await expect(page.locator(".demo-response").last()).toContainText("You spent $754.19 AUD on restaurants last month.");
  await expect(page.locator(".demo-response").last()).toContainText("Scenario used: Incomplete Answer");
  await page.getByRole("button", { name: "Enable Protection Before / After", exact: true }).click();
  await page.getByRole("button", { name: "Run example question" }).click();
  await expect(page.locator(".demo-response").last()).toContainText("unlimited");
  await page.getByLabel("Check and block unsafe answers").click();
  await expect(page.getByLabel("Check and block unsafe answers")).toBeChecked();
  await page.getByRole("button", { name: "Run example question" }).click();
  await expect(page.locator(".demo-response").last()).toContainText("couldn't verify");
  await expect(page.locator(".demo-response").last()).toContainText("Could not be checked");
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
    name: "Enable Galileo",
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
