import { test, expect } from "@playwright/test";

test("add camera, check photos, create, watch and download a video", async ({ page }) => {
  await page.goto("/?empty");
  await page.getByRole("button", { name: "Cameras", exact: true }).click();
  await page.getByRole("button", { name: "Add camera", exact: true }).first().click();
  await page.getByLabel("Camera name", { exact: true }).fill("Test garden");
  await page.getByLabel("Photo folder", { exact: true }).fill("/config/www/garden/snapshots");
  await page.getByLabel("Filename prefix", { exact: true }).fill("garden_");
  await expect(page.getByRole("button", { name: "Save camera", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Check photos", exact: true }).click();
  await expect(page.getByText("2,160 matching photos")).toBeVisible();
  await page.getByRole("button", { name: "Save camera", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Test garden" })).toBeVisible();
  await page.getByRole("article").getByRole("button", { name: "Create video", exact: true }).click();
  await page.getByLabel("Period", { exact: true }).selectOption("custom");
  await page.getByLabel("Start date", { exact: true }).fill("2026-09-01");
  await page.getByLabel("End date", { exact: true }).fill("2026-09-30");
  await page.getByRole("dialog").getByRole("button", { name: "Create video", exact: true }).click();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await page.getByRole("button", { name: "Watch", exact: true }).click();
  await expect(page.locator("video")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("dialog").getByRole("button", { name: "Download", exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/^timelapse_2026-09-01_2026-09-30_/);
});

test("schedule changes persist and Turkish UI is available", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Schedules", exact: true }).click();
  await page.getByRole("checkbox", { name: "Garden overview Previous completed week", exact: true }).check();
  await page.getByRole("button", { name: "Save schedules", exact: true }).first().click();
  await expect(page.getByRole("status")).toHaveText("Schedules saved");
  const enabled = await page.evaluate(() => (window as any).demo.getState().cameras.find((c: any) => c.name === "Garden overview").schedules.weekly.enabled);
  expect(enabled).toBeTruthy();
  await page.getByLabel("Language", { exact: true }).selectOption("tr");
  await expect(page.getByRole("button", { name: "Zamanlama", exact: true })).toBeVisible();
});

test("broken media stops refreshing signed URLs and shows an error", async ({ page }) => {
  let requests = 0;
  await page.route("**/demo.mp4", async route => {
    requests++;
    await route.fulfill({ status: 200, contentType: "video/mp4", body: "invalid video" });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await page.getByRole("button", { name: "Watch", exact: true }).first().click();
  await expect(page.getByRole("alert")).toContainText("Video could not be played");
  expect(requests).toBe(2);
});

test("viewers only see the library and cannot configure or delete", async ({ page }) => {
  await page.goto("/?viewer");
  await expect(page.getByRole("button", { name: "Settings", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cameras", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await expect(page.getByRole("button", { name: "Delete video", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Watch", exact: true })).toHaveCount(3);
});

test("mobile layout fits and can add a source", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?empty&lang=tr");
  await page.getByRole("button", { name: "Kameralar", exact: true }).click();
  await page.getByRole("button", { name: "Kamera ekle", exact: true }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits).toBeTruthy();
});

test("capture documentation screenshots with labeled demo data", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Recent timelapses" })).toBeVisible();
  await page.screenshot({ path: "docs/images/panel.png", fullPage: true });
  await page.getByRole("button", { name: "Cameras", exact: true }).click();
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  await page.screenshot({ path: "docs/images/camera-settings.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?lang=tr");
  await expect(page.getByRole("heading", { name: "Son timelapse videoları" })).toBeVisible();
  await page.screenshot({ path: "docs/images/mobile-tr.png", fullPage: true });
});
