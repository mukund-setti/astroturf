import { describe, it } from "node:test";
import { strict as assert } from "node:assert";

import {
  TOPICS,
  getTopicBySlug,
  topicSlugsForQuery,
  topicForDocket,
} from "../topics";

describe("topics", () => {
  it("includes the-economy as the first user-facing chip", () => {
    assert.equal(TOPICS[0].slug, "the-economy");
  });

  it("getTopicBySlug returns the matching topic", () => {
    const t = getTopicBySlug("banking-and-lending");
    assert.ok(t);
    assert.equal(t!.label, "banking and lending");
  });

  it("getTopicBySlug returns undefined for unknown slug", () => {
    assert.equal(getTopicBySlug("nonsense"), undefined);
  });

  it("topicSlugsForQuery expands the-economy to its children", () => {
    const slugs = topicSlugsForQuery("the-economy");
    assert.deepEqual(slugs, ["the-economy", "banking-and-lending", "labor"]);
  });

  it("topicSlugsForQuery returns just the slug for non-gathering topics", () => {
    assert.deepEqual(topicSlugsForQuery("climate"), ["climate"]);
  });

  it("topicSlugsForQuery falls back to the input slug when topic is unknown", () => {
    assert.deepEqual(topicSlugsForQuery("zzz"), ["zzz"]);
  });

  it("topicForDocket prefers manual mapping over agency fallback", () => {
    assert.equal(topicForDocket("CFPB-2016-0025", "CFPB"), "banking-and-lending");
    assert.equal(topicForDocket("EPA-HQ-OAR-2021-0317", "EPA"), "climate");
    assert.equal(topicForDocket("17-108"), "tech-regulation");
  });

  it("topicForDocket uses agency fallback for unmapped dockets", () => {
    assert.equal(topicForDocket("unknown-1", "DOL"), "labor");
    assert.equal(topicForDocket("unknown-2", "fcc"), "tech-regulation"); // case-insensitive
  });

  it("topicForDocket defaults to the-economy when nothing matches", () => {
    assert.equal(topicForDocket("zzz", "ZZZ"), "the-economy");
    assert.equal(topicForDocket("zzz"), "the-economy");
  });
});
