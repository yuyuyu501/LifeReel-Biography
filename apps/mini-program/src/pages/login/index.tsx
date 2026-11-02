import { useState } from "react";
import { Button, Image, Input, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { miniApi } from "../../shared/api";
import { PreviewNotice } from "../../shared/PreviewNotice";
import { loginCode, miniPlatform } from "../../shared/platform";
import { Icon } from "../../shared/Icon";

export default function LoginPage() {
  const [displayName, setDisplayName] = useState("");
  const [linkExisting, setLinkExisting] = useState(false);
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const login = async () => {
    setLoading(true);
    setError("");
    try {
      const code = await loginCode();
      const auth = linkExisting
        ? await miniApi.linkAccount(
            miniPlatform,
            code,
            account.trim(),
            password,
          )
        : await miniApi.login(
            miniPlatform,
            code,
            displayName.trim() || undefined,
          );
      setPassword("");
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
        <Text className="description">
          已在网页使用过？请选择绑定已有账号，继续使用原有家人、书稿和钱包。
          平台直接登录会为首次使用者建立独立空间，已有的两个空间不会自动合并。
        </Text>
        <Button
          disabled={loading}
          onClick={() => {
            setLinkExisting(!linkExisting);
            setPassword("");
            setError("");
          }}
        >
          {linkExisting ? "返回平台直接登录" : "绑定已有网页账号"}
        </Button>
        {linkExisting ? (
          <>
            <Text className="label">网页账号（手机号或邮箱）</Text>
            <Input
              className="input"
              value={account}
              maxlength={255}
              placeholder="手机号或邮箱"
              disabled={loading}
              onInput={(event) => setAccount(event.detail.value)}
            />
            <Text className="label">网页账号密码</Text>
            <Input
              className="input"
              password
              value={password}
              maxlength={200}
              placeholder="输入网页账号密码"
              disabled={loading}
              onInput={(event) => setPassword(event.detail.value)}
            />
            <Text className="description">
              若此平台身份已经关联另一个账号，会提示冲突并保留原资料；请联系管理员处理。忘记密码可前往网页找回。
            </Text>
          </>
        ) : (
          <>
            <Text className="label">首次使用时的称呼（可选）</Text>
            <Input
              className="input"
              value={displayName}
              maxlength={80}
              placeholder="您的称呼"
              disabled={loading}
              onInput={(event) => setDisplayName(event.detail.value)}
            />
          </>
        )}
        {error ? <Text className="error">{error}</Text> : null}
        <Button
          className="primary-button"
          loading={loading}
          disabled={
            loading ||
            (linkExisting && (!account.trim() || password.length < 8))
          }
          onClick={login}
        >
          {loading
            ? "正在登录"
            : linkExisting
              ? "验证并绑定已有账号"
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
