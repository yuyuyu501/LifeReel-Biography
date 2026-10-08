import { Button, Text, View } from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
export default function ScriptsPage() {
  const subjectId = getCurrentInstance().router?.params?.subjectId || "";
  return (
    <View className="page">
      <Text className="title">剧本与分镜已移到影像</Text>
      <Text className="hint">
        采访填写人生资料，写书保存正文，然后在影像页面选择书稿改编剧本。
      </Text>
      <Button
        onClick={() =>
          Taro.redirectTo({
            url: `/pages/production/index${subjectId ? `?subjectId=${subjectId}` : ""}`,
          })
        }
      >
        前往影像
      </Button>
    </View>
  );
}
