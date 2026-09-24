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
  outputRoot: "dist",
  framework: "react",
  compiler: {
    type: "webpack5",
  },
  mini: {
    postcss: {
      pxtransform: {
        enable: true,
      },
      cssModules: {
        enable: false,
      },
    },
  },
  h5: {},
});

export default config;
