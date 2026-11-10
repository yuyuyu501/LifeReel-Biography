import { PropsWithChildren, useEffect, useState } from "react";
import { Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import "./app.scss";
import { miniApi } from "./shared/api";
import { getStored, loginCode, miniPlatform } from "./shared/platform";

const ACCESS_TOKEN = "lifereel_mini_access_token";

function App({ children }: PropsWithChildren) {
  const [ready, setReady] = useState(process.env.TARO_ENV === "h5");

  useEffect(() => {
    if (process.env.TARO_ENV === "h5" || getStored<string>(ACCESS_TOKEN)) {
      setReady(true);
      return;
    }
    let active = true;
    (async () => {
      try {
        const auth = await miniApi.login(miniPlatform, await loginCode());
        miniApi.saveAuth(auth);
      } catch {
        if (active) {
          void Taro.reLaunch({ url: "/pages/login/index" });
        }
      } finally {
        if (active) setReady(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (!ready && process.env.TARO_ENV !== "h5") {
    return (
      <View className="page login-page">
        <Text className="empty">正在使用当前平台账号登录……</Text>
      </View>
    );
  }
  return children;
}

export default App;
