import { resolve } from "node:path";
import { defineConfig, type UserConfigExport } from "@tarojs/cli";

const config: UserConfigExport = defineConfig({
  projectName: "lifereel-mini-program",
  date: "2026-09-24",
  designWidth: 750,
  deviceRatio: {
    640: 2.34 / 2,
    750: 1,
    828: 1.81 / 2,
  },
  sourceRoot: "src",
  outputRoot: `dist/${process.env.TARO_ENV === "h5" ? "preview" : process.env.TARO_ENV || "weapp"}`,
  framework: "react",
  compiler: {
    type: "webpack5",
  },
  mini: {
    // Taro treats zero as the default inline threshold; keep native Image sources as files.
    imageUrlLoaderOption: { limit: 1 },
    compile: { include: [resolve(__dirname, "../../../packages/contracts")] },
    postcss: {
      pxtransform: {
        enable: true,
        config: { propList: ["*", "!font-size", "!min-height", "!min-width"] },
      },
      cssModules: {
        enable: false,
      },
    },
  },
  h5: {
    compile: { include: [resolve(__dirname, "../../../packages/contracts")] },
    publicPath: "/",
    router: { mode: "hash" },
    postcss: {
      pxtransform: {
        enable: true,
        config: {
          propList: ["*", "!font-size", "!min-height", "!min-width"],
          baseFontSize: 20,
          minRootSize: 1,
          maxRootSize: 22.9333333333,
        },
      },
    },
    devServer: { host: "127.0.0.1", port: 5175, hot: false },
  },
});

export default config;
