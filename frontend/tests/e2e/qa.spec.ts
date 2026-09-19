import { test, expect, type Page } from "@playwright/test";

/** 规格 10.1 E2E 层最小验收：登录 → 规范问答 SSE → 方案A 角色路由守卫 → 培训管理台可达 */
async function login(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("button[type=submit]").click();
  await page.waitForURL(/\/qa/, { timeout: 15_000 });
}

test("登录后进入规范问答并完成一次 SSE 问答", async ({ page }) => {
  await login(page, "qa_user1", "QaPass@123456");
  await expect(page).toHaveURL(/\/qa/);

  const textarea = page.locator("textarea");
  await textarea.fill("纯化水系统日常监测的检测频次应依据什么规定？");
  await page.locator("button", { hasText: "发送" }).click();

  // 等待回答内容出现（stub 编排 + rerank，SSE 多段 delta）
  await expect(page.locator("text=/纯化水|制药用水|监测/").first()).toBeVisible({
    timeout: 90_000,
  });
});

test("方案A：qa 角色访问 /training 被守卫重定向，且导航无培训入口", async ({ page }) => {
  await login(page, "qa_user1", "QaPass@123456");
  await page.goto("/training");
  await expect(page).toHaveURL(/\/qa/); // 白名单 operator/crc，非考生角色被导回
  await expect(page.locator("nav")).not.toContainText("培训认证");
  await expect(page.locator("nav")).not.toContainText("培训管理");
});

test("trainer/admin 可进入培训管理工作台并加载题库", async ({ page }) => {
  await login(page, "admin", "Admin@123456");
  await page.goto("/training/manage");
  await expect(page.locator("h2")).toContainText("培训管理工作台");
  await expect(page.locator("text=/题库维护|组卷发布|认证签发/").first()).toBeVisible();
  // 默认题库 Tab 展示数据表格（存在任意行或空态文案均视为 API 联通）
  await expect(page.locator(".table-wrap")).toBeVisible({ timeout: 20_000 });
});
