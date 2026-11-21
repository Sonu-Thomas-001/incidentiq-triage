import { test, type Page } from "@playwright/test";
import path from "node:path";

// Captures documentation screenshots from the real stack. Run: CAPTURE=1 npm run e2e -- screenshots
test.skip(!process.env.CAPTURE, "set CAPTURE=1 to regenerate docs screenshots");

const PASSWORD = process.env.E2E_PASSWORD ?? "E2e-Pass-123!";
const out = path.resolve(import.meta.dirname, "..", "..", "docs", "presentation", "screenshots");

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Sign out" }).waitFor();
}

test("capture pages", async ({ page }) => {
  const shot = async (name: string, full = true) => {
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: full });
  };
  await page.goto("/login");
  await shot("00-login", false);
  await login(page, "analyst@synthetic.example");
  await page.goto("/");
  await shot("01-overview");
  await page.goto("/incidents");
  await shot("02-explorer");
  await page.getByRole("table").getByRole("link").first().click();
  await page.getByRole("heading", { name: "AI Triage Workspace" }).waitFor();
  await shot("04-triage-workspace");
  await page.getByRole("link", { name: /Full audit timeline/ }).click();
  await shot("07-audit-timeline");
  await page.goto("/incidents/new");
  await shot("03-create-incident");
  await page.goto("/queues");
  await shot("05-team-queues");
  await page.goto("/analytics");
  await page.getByRole("heading", { name: "Analytics" }).waitFor();
  await shot("06-analytics");
  await page.goto("/admin");
  await shot("08-admin-settings");
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await shot("09-mobile-overview");
});
