import { describe, it, expect } from "vitest";
import { statusMeta } from "./status";

describe("statusMeta", () => {
  it("uses the active trigger as the headline", () => {
    expect(statusMeta("wheel_spin", true).label).toBe("Wheel-spinning");
    expect(statusMeta("explorer", true).label).toBe("Explorer");
  });
  it("is OK when there is data but no active trigger", () => {
    expect(statusMeta(null, true).label).toBe("OK");
  });
  it("is No data when the student has no materialized state", () => {
    expect(statusMeta(null, false).label).toBe("No data");
  });
});
