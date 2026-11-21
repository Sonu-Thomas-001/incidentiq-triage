import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "E2e-Pass-123!";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

test("rejects bad credentials with a visible error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("analyst@synthetic.example");
  await page.getByLabel("Password").fill("definitely-wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  await expect(page.getByRole("alert").or(page.getByText(/invalid|incorrect|failed/i)).first()).toBeVisible();
});

test("reporter does not see staff navigation and cannot open staff pages", async ({ page }) => {
  await login(page, "reporter@synthetic.example");
  await expect(page.getByRole("link", { name: "Analytics" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Admin Settings" })).toHaveCount(0);
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Analytics" })).toHaveCount(0);
});

test("incident lifecycle: create -> triage -> approve -> accept, with audit trail", async ({ page }) => {
  const title = `E2E VPN drops every hour ${Date.now()}`;

  await login(page, "reporter@synthetic.example");
  await page.goto("/incidents/new");
  await page.getByLabel("Short description").fill(title);
  await page.getByLabel("Detailed description").fill("The VPN client disconnects roughly every hour and needs a manual reconnect. Started after the last client update.");
  await page.getByLabel("Service").fill("VPN");
  await page.getByRole("button", { name: /create|submit/i }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  await logout(page);

  await login(page, "analyst@synthetic.example");
  await page.goto("/incidents");
  await page.getByRole("searchbox").or(page.getByPlaceholder(/search/i)).first().fill(title);
  await page.getByRole("link", { name: new RegExp(title) }).first().click();
  await expect(page.getByRole("heading", { name: "AI Triage Workspace" })).toBeVisible();
  await expect(page.getByText(title).first()).toBeVisible();

  await page.getByRole("button", { name: /Run triage/ }).click();
  await expect(page.getByText("NEEDS_REVIEW").or(page.getByText(/needs review/i)).first()).toBeVisible();
  // Recommendations are labelled; no ServiceNow write happens here.
  await expect(page.getByText(/Recommendation only|DEMO/i).first()).toBeVisible();

  const sel = page.getByLabel("Assign to team");
  const value = await sel.locator("option", { hasText: "Network Operations" }).first().getAttribute("value");
  await sel.selectOption(value!);
  const reason = page.getByLabel(/Reason/);
  if (await reason.isVisible()) await reason.fill("E2E analyst decision: VPN is a network service.");
  await page.getByRole("button", { name: /Approve|Override/ }).first().click();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Network Operations").first()).toBeVisible();
  await expect(page.getByText(/ASSIGNED/).first()).toBeVisible();
  await logout(page);

  await login(page, "engineer.network@synthetic.example");
  await page.goto("/queues");
  await expect(page.getByText(title).first()).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(title) });
  await row.getByRole("button", { name: "Accept" }).click();
  await expect(row.getByRole("button", { name: "Accept" })).toHaveCount(0);
  await expect(row.getByText("ACCEPTED", { exact: false })).toBeVisible();

  await page.getByRole("link", { name: new RegExp(title) }).first().click();
  await page.getByRole("link", { name: /Full audit timeline/ }).click();
  await expect(page.getByText(/created/i).first()).toBeVisible();
  await expect(page.getByText(/accept/i).first()).toBeVisible();
});

test("mobile layout exposes navigation through the menu button", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await login(page, "analyst@synthetic.example");
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("link", { name: "Incident Explorer" })).toBeVisible();
});
