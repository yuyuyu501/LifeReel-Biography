const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { test } = require("node:test");
const assert = require("node:assert/strict");

test("mini-program distribution excludes video routes and navigation", () => {
  const source = (path) =>
    readFileSync(resolve(__dirname, "../src", path), "utf8");
  assert.doesNotMatch(
    source("app.config.ts"),
    /pages\/(?:production|scripts)\//,
  );
  assert.doesNotMatch(source("shared/PageFrame.tsx"), /key: "production"/);
  assert.doesNotMatch(
    source("pages/home/index.tsx"),
    /page: "production"|guide-home-production/,
  );
  assert.doesNotMatch(
    source("pages/books/index.tsx"),
    /pages\/production\/|guide-book-adapt/,
  );
});
