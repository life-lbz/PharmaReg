import { describe, it, expect } from "vitest";
import { hasPermission } from "../src/lib/auth";
import type { UserInfo } from "../src/lib/auth";

const admin: UserInfo = {
  id: 1,
  username: "admin",
  display_name: "管理员",
  employee_no: "A-1",
  roles: ["admin"],
  permissions: ["*"],
};

const operator: UserInfo = {
  id: 2,
  username: "op",
  display_name: "操作工",
  employee_no: "O-1",
  roles: ["operator"],
  permissions: ["qa.ask", "training.take"],
};

describe("权限点判断 hasPermission", () => {
  it("admin 通配符 * 放行一切权限点", () => {
    expect(hasPermission(admin, "deviation.review")).toBe(true);
    expect(hasPermission(admin, "kb.activate")).toBe(true);
  });

  it("按角色权限点精确匹配", () => {
    expect(hasPermission(operator, "training.take")).toBe(true);
    expect(hasPermission(operator, "kb.manage")).toBe(false);
  });

  it("null 用户一律拒绝", () => {
    expect(hasPermission(null, "qa.ask")).toBe(false);
  });
});
