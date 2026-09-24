export default defineAppConfig({
  pages: [
    "pages/home/index",
    "pages/login/index",
    "pages/interview/index",
    "pages/memory/index",
    "pages/scripts/index",
    "pages/production/index",
  ],
  window: {
    navigationBarTitleText: "岁忆影传",
    navigationBarBackgroundColor: "#f7f4ee",
    navigationBarTextStyle: "black",
    backgroundColor: "#f7f4ee",
  },
  lazyCodeLoading: "requiredComponents",
});
