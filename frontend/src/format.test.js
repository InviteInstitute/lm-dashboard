import { describe, it, expect } from "vitest";
import { relTime, fmtDur, statusMeta, parseTs, noteTime } from "./CohortDashboard.jsx";

describe("relTime", () => {
  it("shows a dash for missing input", () => {
    expect(relTime(null)).toBe("-");
  });
  it("renders seconds / minutes / hours / days by magnitude", () => {
    const ago = (s) => new Date(Date.now() - s * 1000).toISOString();
    expect(relTime(ago(10))).toBe("10s");
    expect(relTime(ago(120))).toBe("2m");
    expect(relTime(ago(7200))).toBe("2h");
    expect(relTime(ago(2 * 86400))).toBe("2d");
  });
  it("never goes negative for a future timestamp", () => {
    expect(relTime(new Date(Date.now() + 60000).toISOString())).toBe("0s");
  });
});

describe("fmtDur", () => {
  it("shows a dash for null", () => {
    expect(fmtDur(null)).toBe("-");
  });
  it("formats whole units, largest first", () => {
    expect(fmtDur(5)).toBe("5s");
    expect(fmtDur(40.4)).toBe("40s");
    expect(fmtDur(90)).toBe("1m 30s");
    expect(fmtDur(120)).toBe("2m");
    expect(fmtDur(5400)).toBe("1h 30m");
    expect(fmtDur(7200)).toBe("2h");
  });
});

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

describe("parseTs", () => {
  it("reads a bare DB timestamp as UTC, not local time", () => {
    expect(parseTs("2026-09-25 01:57:18.055110").toISOString()).toBe("2026-09-25T01:57:18.055Z");
  });
  it("keeps an explicit offset", () => {
    expect(parseTs("2026-07-21T10:24:00+00:00").toISOString()).toBe("2026-07-21T10:24:00.000Z");
  });
  it("returns null for missing or garbage input", () => {
    expect(parseTs(null)).toBeNull();
    expect(parseTs("not a time")).toBeNull();
  });
});

describe("noteTime", () => {
  const at = (y, mo, d, h, mi) => new Date(y, mo - 1, d, h, mi); // local time
  const iso = (dt) => dt.toISOString().replace("T", " ").replace("Z", "000"); // DB-style UTC
  const now = at(2026, 9, 25, 14, 0);
  const clock = (dt) => dt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  it("shows only the time for today", () => {
    const t = at(2026, 9, 25, 8, 57);
    expect(noteTime(iso(t), now)).toBe(clock(t));
  });
  it("says Yesterday for the previous day", () => {
    const t = at(2026, 9, 24, 20, 57);
    expect(noteTime(iso(t), now)).toBe(`Yesterday, ${clock(t)}`);
  });
  it("shows month and day for older notes, and the year once it differs", () => {
    const t = at(2026, 9, 23, 9, 5);
    expect(noteTime(iso(t), now)).toMatch(/^Sep 23, /);
    expect(noteTime(iso(at(2025, 12, 30, 9, 5)), now)).toMatch(/2025/);
  });
  it("falls back to the raw value when it cannot parse", () => {
    expect(noteTime("10:14 AM", now)).toBe("10:14 AM");
  });
});
