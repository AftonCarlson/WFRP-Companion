import { describe, expect, it } from "vitest";

import {
  nextPdfPage,
  previousPdfPage,
  visiblePdfPages,
} from "./pdfPages";

describe("pdfPages", () => {
  it("shows one page in single-page mode", () => {
    expect(visiblePdfPages(3, 10, "single")).toEqual([3]);
  });

  it("keeps the first two pages alone in two-page mode", () => {
    expect(visiblePdfPages(1, 10, "two-page")).toEqual([1]);
    expect(visiblePdfPages(2, 10, "two-page")).toEqual([2]);
  });

  it("pairs pages after the first two pages in two-page mode", () => {
    expect(visiblePdfPages(3, 10, "two-page")).toEqual([3, 4]);
    expect(visiblePdfPages(4, 10, "two-page")).toEqual([3, 4]);
    expect(visiblePdfPages(5, 10, "two-page")).toEqual([5, 6]);
  });

  it("keeps an unpaired final page alone in two-page mode", () => {
    expect(visiblePdfPages(9, 9, "two-page")).toEqual([9]);
  });

  it("moves by visible spreads in two-page mode", () => {
    expect(nextPdfPage(1, 10, "two-page")).toBe(2);
    expect(nextPdfPage(2, 10, "two-page")).toBe(3);
    expect(nextPdfPage(3, 10, "two-page")).toBe(5);
    expect(nextPdfPage(4, 10, "two-page")).toBe(5);
    expect(previousPdfPage(5, 10, "two-page")).toBe(3);
    expect(previousPdfPage(3, 10, "two-page")).toBe(2);
    expect(previousPdfPage(2, 10, "two-page")).toBe(1);
    expect(previousPdfPage(1, 10, "two-page")).toBe(1);
  });

  it("does not advance past a final paired spread in two-page mode", () => {
    expect(nextPdfPage(8, 8, "two-page")).toBe(8);
    expect(nextPdfPage(7, 8, "two-page")).toBe(7);
  });
});
