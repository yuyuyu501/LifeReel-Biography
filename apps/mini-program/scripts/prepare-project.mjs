import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const platform = process.argv[2];
if (!["weapp", "tt"].includes(platform)) throw new Error("请选择 weapp 或 tt");
const envFile = resolve(root, ".env.local");
const localEnv = {};
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const match = line.match(/^([A-Z_]+)\s*=\s*(.*?)\s*$/);
    if (match) localEnv[match[1]] = match[2].replace(/^(["'])(.*)\1$/, "$2");
  }
}
const key = platform === "weapp" ? "WECHAT_APP_ID" : "DOUYIN_APP_ID";
const output = resolve(
  root,
  platform === "weapp" ? "project.config.json" : "project.tt.json",
);
const existing = existsSync(output)
  ? JSON.parse(readFileSync(output, "utf8"))
  : {};
const appid = process.env[key] || localEnv[key] || existing.appid || "";
if (
  appid &&
  !(platform === "weapp" ? /^wx[a-zA-Z0-9]{16}$/ : /^tt[a-zA-Z0-9]+$/).test(
    appid,
  )
)
  throw new Error(`${key} 格式不正确，请从平台控制台复制真实 AppID`);
const config = {
  description: "岁忆影传小程序",
  projectname: "lifereel-mini-program",
  ...existing,
  appid,
  compileType: "miniprogram",
  miniprogramRoot: "./",
  setting: {
    urlCheck: true,
    es6: false,
    postcss: false,
    minified: true,
    ...existing.setting,
  },
};
writeFileSync(output, JSON.stringify(config, null, 2) + "\n");
console.log(
  `${platform} 导入配置已生成${appid ? "（已读取 AppID）" : "（未配置 AppID，不能上传或完成真实登录）"}。构建后导入 apps/mini-program/dist/${platform}。`,
);
