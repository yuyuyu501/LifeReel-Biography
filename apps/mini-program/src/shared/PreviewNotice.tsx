import { Text, View } from "@tarojs/components";

export function PreviewNotice() {
  if (process.env.TARO_ENV !== "h5") return null;
  return (
    <View className="preview-notice">
      <Text className="preview-dot" />
      <Text>本地模拟数据 · 无真实调用</Text>
    </View>
  );
}
