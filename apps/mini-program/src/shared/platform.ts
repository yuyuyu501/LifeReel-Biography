import Taro from "@tarojs/taro";

export type MiniPlatform = "wechat" | "douyin";

export const miniPlatform: MiniPlatform =
  process.env.TARO_ENV === "tt" ? "douyin" : "wechat";

export function loginCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    Taro.login({
      success: (result) => resolve(result.code),
      fail: reject,
    });
  });
}

export function getStored<T>(key: string): T | null {
  return Taro.getStorageSync<T>(key) || null;
}

export function store(key: string, value: unknown): void {
  Taro.setStorageSync(key, value);
}

export function removeStored(key: string): void {
  Taro.removeStorageSync(key);
}
