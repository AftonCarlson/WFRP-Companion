import { describe, expect, it } from "vitest";

import { ApiError, errorMessage } from "./apiError";

describe("errorMessage", () => {
  it("normalizes API, native, and unknown errors", () => {
    expect(errorMessage(new ApiError(404, "Missing"))).toBe("Missing");
    expect(errorMessage(new Error("Broken"))).toBe("Broken");
    expect(errorMessage("not an error")).toBe("Unknown error");
  });
});
