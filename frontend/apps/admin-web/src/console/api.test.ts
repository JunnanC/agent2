import { beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "@edu/auth-client";
import {
  imageAddress,
  listAll,
  splitAccounts,
  usage,
  type Account,
  type Role,
} from "./api";

vi.mock("@edu/auth-client", () => ({ request: vi.fn() }));
const mockRequest = vi.mocked(request);
beforeEach(() => mockRequest.mockReset());

describe("management data boundaries", () => {
  it("loads all server pages before computing role counts", async () => {
    mockRequest.mockResolvedValueOnce({
      data: Array.from({ length: 100 }, (_, id) => ({ id })),
      meta: { total: 101 },
    });
    mockRequest.mockResolvedValueOnce({
      data: [{ id: 100 }],
      meta: { total: 101 },
    });
    const signal = new AbortController().signal;
    const rows = await listAll("/platform/users", signal);
    expect(rows).toHaveLength(101);
    expect(mockRequest).toHaveBeenLastCalledWith("/platform/users", {
      query: { page: 2, page_size: 100 },
      signal,
    });
  });
  it("does not present incomplete pagination as a complete list", async () => {
    mockRequest.mockResolvedValue({ data: [], meta: { total: 10 } });
    await expect(listAll("/platform/users")).rejects.toThrow("列表加载不完整");
  });
  it("does not misclassify teachers or admins as students", () => {
    const accounts = ["s", "t", "a", "both"].map((public_id) => ({
      public_id,
    })) as Account[];
    const teachers = ["t", "both"].map((user_id) => ({ user_id })) as Role[];
    const admins = ["a", "both"].map((user_id) => ({ user_id })) as Role[];
    expect(
      splitAccounts(accounts, teachers, admins).students.map(
        (u) => u.public_id,
      ),
    ).toEqual(["s"]);
    expect(
      splitAccounts(accounts, teachers, admins).teachers.map(
        (u) => u.public_id,
      ),
    ).toEqual(["t", "both"]);
  });
  it("distinguishes absent capacity from zero consumption", () => {
    expect(usage(0, 0)).toBeNull();
    expect(usage(100, undefined)).toBeNull();
    expect(usage(100, 100)).toBe(0);
    expect(usage(100, 150)).toBe(0);
    expect(usage(100, -20)).toBe(100);
  });
  it("preserves registry ports and separates image version from address", () => {
    expect(
      imageAddress("https://registry.school.edu:5000/labs/python"),
    ).toEqual({
      registry: "registry.school.edu:5000",
      repository: "labs/python",
    });
    expect(() => imageAddress("registry.school.edu/labs/python:v1")).toThrow(
      "版本",
    );
    expect(() => imageAddress("python")).toThrow("镜像地址");
    expect(() =>
      imageAddress("https://registry.school.edu/labs/x?token=secret"),
    ).toThrow();
  });
});
