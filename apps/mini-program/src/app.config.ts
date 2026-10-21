export default defineAppConfig({
  pages: [
    "pages/home/index",
    "pages/login/index",
    "pages/interview/index",
    "pages/profile/index",
    "pages/books/index",
    "pages/memory/index",
    "pages/scripts/index",
    "pages/production/index",
  ],
  window: {
    navigationBarTitleText: "岁忆影传",
    navigationBarBackgroundColor: "#f5f8f7",
    navigationBarTextStyle: "black",
    backgroundColor: "#f5f8f7",
  },
  lazyCodeLoading: "requiredComponents",
});
