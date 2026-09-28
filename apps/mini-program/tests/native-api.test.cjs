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
