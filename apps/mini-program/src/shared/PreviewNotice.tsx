import { Button, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";

export function PreviewNotice() {
  if (process.env.TARO_ENV !== "h5") return null;
  return (
    <View className="preview-notice">
      <Text>小程序界面预览 · 本地模拟数据</Text>
      <Text className="preview-detail">
        不连接线上，不调用 AI 或支付；刷新恢复示例。
      </Text>
      <View className="action-row">
        <Button
          className="text-button"
          onClick={() => Taro.reLaunch({ url: "/pages/home/index" })}
        >
          预览首页
        </Button>
        <Button
          className="text-button"
          onClick={() => Taro.reLaunch({ url: "/pages/login/index" })}
        >
          登录界面
        </Button>
      </View>
    </View>
  );
}
