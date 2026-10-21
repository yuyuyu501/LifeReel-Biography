import { useState } from "react";
import { Button, Image, Input, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { miniApi } from "../../shared/api";
import { PreviewNotice } from "../../shared/PreviewNotice";
import { loginCode, miniPlatform } from "../../shared/platform";
import { Icon } from "../../shared/Icon";

export default function LoginPage() {
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const login = async () => {
    setLoading(true);
    setError("");
    try {
      const code = await loginCode();
      const auth = await miniApi.login(
        miniPlatform,
        code,
        displayName.trim() || undefined,
      );
      miniApi.saveAuth(auth);
      Taro.reLaunch({ url: "/pages/home/index" });
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "登录失败，请稍后重试",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <View className="page login-page">
      <PreviewNotice />
      <View className="login-identity">
        <Text className="brand-mark">岁</Text>
        <Text className="title">岁忆影传</Text>
        <Text className="description">把人生故事，留给家人。</Text>
      </View>
      <Image
        src={require("../../assets/interview.png")}
        className="login-art"
        mode="aspectFit"
      />
      <View className="login-form">
        <Text className="label">首次使用时的称呼（可选）</Text>
        <Input
          className="input"
          value={displayName}
          maxlength={80}
          placeholder="您的称呼"
          disabled={loading}
          onInput={(event) => setDisplayName(event.detail.value)}
        />
        {error ? <Text className="error">{error}</Text> : null}
        <Button
          className="primary-button"
          loading={loading}
          disabled={loading}
          onClick={login}
        >
          {loading
            ? "正在登录"
            : process.env.TARO_ENV === "h5"
              ? "进入本地预览"
              : `使用${miniPlatform === "wechat" ? "微信" : "抖音"}登录`}
        </Button>
      </View>
      <View className="login-footer privacy-label">
        <Icon name="lock" tone="muted" />
        <Text>家庭故事 · 私密保存</Text>
      </View>
    </View>
  );
}
