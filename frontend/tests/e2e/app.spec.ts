import { test, expect } from "@playwright/test";

test("renders the main workflow shell", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Visual Network and Change Management")).toBeVisible();
  await expect(page.getByText("GNS3 Connection")).toBeVisible();
  await expect(page.getByText("Deployment Progress")).toBeVisible();
});
