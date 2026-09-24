import { useState } from "react";
import { Button, Input, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { miniApi } from "../../shared/api";
import { loginCode, miniPlatform } from "../../shared/platform";

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
      <View className="hero">
        <Text className="eyebrow">LIFEREEL BIOGRAPHY</Text>
        <Text className="title">把人生故事，留给家人</Text>
        <Text className="description">
          登录后开始记录人物、章节和采访内容。
        </Text>
      </View>
      <View className="card">
        <Text className="label">首次使用时的称呼（可选）</Text>
        <Input
          className="input"
          value={displayName}
          maxlength={80}
          placeholder="例如：林女士"
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
            : `使用${miniPlatform === "wechat" ? "微信" : "抖音"}登录`}
        </Button>
        <Text className="hint">
          登录失败时，请确认小程序已配置到服务器白名单。
        </Text>
      </View>
    </View>
  );
}
