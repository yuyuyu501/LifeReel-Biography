const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const compiled = ts.transpileModule(
  fs.readFileSync(path.join(__dirname, "../src/shared/api.ts"), "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  },
).outputText;
function setup(replies, page = "pages/home/index") {
  const storage = new Map();
  const calls = [];
  const navigations = [];
  const taro = {
    request: async (options) => {
      calls.push(options);
      assert.ok(replies.length, "unexpected request");
      return replies.shift();
    },
    getCurrentInstance: () => ({ router: { path: page } }),
    reLaunch: async (options) => {
      navigations.push(options.url);
    },
  };
  const module = { exports: {} };
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    process: { env: { TARO_APP_API_BASE_URL: "https://test.invalid" } },
    require: (name) => {
      if (name === "@tarojs/taro") return taro;
      if (name === "./platform")
        return {
          getStored: (key) => storage.get(key),
          store: (key, value) => storage.set(key, value),
          removeStored: (key) => storage.delete(key),
        };
      throw new Error(`Unexpected module ${name}`);
    },
  });
  return { api: module.exports.miniApi, storage, calls, navigations };
}
test("unauthorized first visit opens login and clears stale identity", async () => {
  const { api, storage, navigations } = setup([{ statusCode: 401, data: {} }]);
  storage.set("lifereel_mini_access_token", "stale");
  await assert.rejects(api.me(), /401/);
  assert.deepEqual(navigations, ["/pages/login/index"]);
  assert.equal(storage.has("lifereel_mini_access_token"), false);
});
for (const page of ["pages/login/index", "/pages/login/index"]) {
  test(`login failure does not redirect in ${page}`, async () => {
    const { api, navigations } = setup([{ statusCode: 401, data: {} }], page);
    await assert.rejects(api.login("wechat", "invalid-test-code"), /401/);
    assert.equal(navigations.length, 0);
  });
}
test("expired token refreshes and replays with the new bearer token", async () => {
  const auth = {
    access_token: "new-test-token",
    refresh_token: "new-test-refresh",
    user: { id: "test-user" },
  };
  const { api, storage, calls, navigations } = setup([
    { statusCode: 401, data: {} },
    { statusCode: 200, data: auth },
    { statusCode: 200, data: [] },
  ]);
  storage.set("lifereel_mini_access_token", "old-test-token");
  storage.set("lifereel_mini_refresh_token", "old-test-refresh");
  assert.deepEqual(await api.persons(), []);
  assert.equal(calls[0].header.Authorization, "Bearer old-test-token");
  assert.equal(
    calls[1].url,
    "https://test.invalid/v1/auth/mini-program/refresh",
  );
  assert.equal(calls[2].header.Authorization, "Bearer new-test-token");
  assert.equal(navigations.length, 0);
});

test("whole-book adaptation sends the book without a fixed duration or chapter selection", async () => {
  const { api, calls } = setup([{ statusCode: 201, data: { id: "script" } }]);
  const payload = {
    subject_id: "person",
    book_id: "book",
    mode: "multi_chapter",
    audience: "family",
    idempotency_key: "request",
    adaptation_instructions: "保留家乡细节",
  };
  await api.generateScript(payload);
  assert.equal(calls[0].url, "https://test.invalid/v1/scripts/generate");
  assert.equal(calls[0].method, "POST");
  assert.deepEqual(calls[0].data, payload);
  assert.equal("duration_seconds" in calls[0].data, false);
  assert.equal("book_revision_ids" in calls[0].data, false);
});

test("preview profile labels match the canonical server template", () => {
  const root = path.resolve(__dirname, "../../..");
  const canonical = fs.readFileSync(
    path.join(
      root,
      "services/interview/src/lifereel_api/modules/interview/profile_template.py",
    ),
    "utf8",
  );
  const read = (name) =>
    JSON.parse(
      canonical.match(
        new RegExp(`${name} = json.loads\\(r"""([\\s\\S]*?)"""\\)`),
      )[1],
    );
  const source = fs.readFileSync(
    path.join(root, "packages/contracts/src/life-profile-template.ts"),
    "utf8",
  );
  const templateModule = { exports: {} };
  vm.runInNewContext(
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS },
    }).outputText,
    { exports: templateModule.exports },
  );
  const template = JSON.parse(
    JSON.stringify(templateModule.exports.lifeProfileTemplate),
  );
  assert.equal(template.fields.length, 67);
  assert.deepEqual(template, {
    fields: read("FIELDS"),
    sections: read("SECTIONS"),
  });
  assert.equal(source.includes("\uFFFD"), false);
});
