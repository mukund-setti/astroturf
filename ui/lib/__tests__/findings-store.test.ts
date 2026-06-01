// Pure-helper tests for findings-store. The data-layer functions need a
// live database and aren't exercised here; we cover slug generation and
// date-range formatting, which are the parts most likely to silently rot.
//
// Module-level DATABASE_URL guard is satisfied by lib/__tests__/setup.ts,
// which runs via `node --import` before this module is loaded.

import { describe, it } from "node:test";
import { strict as assert } from "node:assert";

import { makeSlug, formatDateRange } from "../findings-store";

describe("makeSlug", () => {
  it("produces a kebab-cased headline with deterministic suffix", () => {
    const slug = makeSlug("The payday lending fight", "abc123");
    assert.match(slug, /^the-payday-lending-fight-[0-9a-f]{6}$/);
  });

  it("is deterministic across calls for the same cluster_id", () => {
    const a = makeSlug("Headline one", "cluster-x");
    const b = makeSlug("Headline one", "cluster-x");
    assert.equal(a, b);
  });

  it("produces a different suffix for different cluster_ids even with same headline", () => {
    const a = makeSlug("Same words", "cluster-a");
    const b = makeSlug("Same words", "cluster-b");
    assert.notEqual(a, b);
  });

  it("ignores headline punctuation and casing", () => {
    const slug = makeSlug("WHAT?! A 'Surprise'", "x");
    assert.match(slug, /^what-a-surprise-[0-9a-f]{6}$/);
  });

  it("falls back to finding-<hash> when headline yields no slug chars", () => {
    const slug = makeSlug("!!! ???", "x");
    assert.match(slug, /^finding-[0-9a-f]{6}$/);
  });

  it("caps the slug base at 60 characters", () => {
    const long = "a".repeat(200);
    const slug = makeSlug(long, "x");
    const base = slug.split("-").slice(0, -1).join("-");
    assert.ok(base.length <= 60, `expected base <= 60 chars, got ${base.length}`);
  });
});

describe("formatDateRange", () => {
  it("returns null when both bounds are null", () => {
    assert.equal(formatDateRange(null, null), null);
  });

  it("returns a single date when both bounds are the same day", () => {
    assert.equal(
      formatDateRange(
        "2016-06-10T12:00:00Z",
        "2016-06-10T19:00:00Z",
      ),
      "2016-06-10",
    );
  });

  it("returns a 'start to end' range across different days", () => {
    assert.equal(
      formatDateRange("2016-06-10T00:00:00Z", "2016-06-16T23:59:59Z"),
      "2016-06-10 to 2016-06-16",
    );
  });

  it("handles a single-sided range", () => {
    assert.equal(formatDateRange("2020-01-01T00:00:00Z", null), "2020-01-01");
    assert.equal(formatDateRange(null, "2020-01-01T00:00:00Z"), "2020-01-01");
  });

  it("accepts plain YYYY-MM-DD strings", () => {
    assert.equal(formatDateRange("2017-08-28", "2017-08-28"), "2017-08-28");
  });
});
