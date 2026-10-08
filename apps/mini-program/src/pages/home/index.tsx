import { useEffect, useState } from "react";
import { Button, Input, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import type { Person } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { PreviewNotice } from "../../shared/PreviewNotice";
import { miniPlatform } from "../../shared/platform";

export default function HomePage() {
  const [user, setUser] = useState<{ display_name: string } | null>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [newPersonName, setNewPersonName] = useState("");
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([miniApi.me(), miniApi.persons()])
      .then(([me, people]) => {
        setUser(me);
        setPersons(people);
        setSelectedPersonId(people[0]?.id || "");
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "内容加载失败"),
      );
  }, []);

  const logout = () => {
    miniApi.clearAuth();
    Taro.reLaunch({ url: "/pages/login/index" });
  };

  const createPerson = async () => {
    const name = newPersonName.trim();
    if (!name) return;
    try {
      const person = await miniApi.createPerson({ display_name: name });
      setPersons((items) => [...items, person]);
      setSelectedPersonId(person.id);
      setNewPersonName("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "人物创建失败");
    }
  };

  const open = (url: string) => Taro.navigateTo({ url });

  return (
    <View className="page home-page">
      <PreviewNotice />
      <View className="home-header">
        <View>
          <Text className="eyebrow">LIFEREEL BIOGRAPHY</Text>
          <Text className="title">
            {user ? `${user.display_name}，你好` : "正在加载"}
          </Text>
        </View>
        <Button className="text-button" onClick={logout}>
          退出
        </Button>
      </View>
      {error ? <Text className="error">{error}</Text> : null}
      <View className="section">
        <Text className="section-title">人物</Text>
        <View className="list-card">
          <Input
            className="input compact-input"
            value={newPersonName}
            placeholder="新增人物姓名"
            onInput={(event) => setNewPersonName(event.detail.value)}
          />
          <Button className="primary-button" onClick={createPerson}>
            创建人物
          </Button>
        </View>
        {persons.length ? (
          persons.map((person) => (
            <View
              className="list-card"
              key={person.id}
              onClick={() => setSelectedPersonId(person.id)}
            >
              <Text className="list-title">{person.display_name}</Text>
              <Text className="list-meta">
                {person.birth_year
                  ? `${person.birth_year} 年`
                  : "尚未填写出生年份"}
              </Text>
              {selectedPersonId === person.id ? (
                <View className="action-row">
                  <Button
                    className="secondary-button"
                    onClick={() =>
                      open(`/pages/interview/index?subjectId=${person.id}`)
                    }
                  >
                    开始采访
                  </Button>
                  <Button
                    className="secondary-button"
                    onClick={() =>
                      open(`/pages/memory/index?subjectId=${person.id}`)
                    }
                  >
                    记忆图谱
                  </Button>
                  <Button
                    className="secondary-button"
                    onClick={() =>
                      open(`/pages/profile/index?subjectId=${person.id}`)
                    }
                  >
                    人生资料表
                  </Button>
                  <Button
                    className="secondary-button"
                    onClick={() =>
                      open(`/pages/books/index?subjectId=${person.id}`)
                    }
                  >
                    写书
                  </Button>
                </View>
              ) : null}
            </View>
          ))
        ) : (
          <Text className="empty">还没有人物资料</Text>
        )}
      </View>
      <View className="section">
        <Text className="section-title">生产</Text>
        <Button
          className="secondary-button"
          onClick={() => open("/pages/production/index")}
        >
          查看视频任务
        </Button>
      </View>
      <View className="section">
        <Text className="section-title">账户充值</Text>
        <Button className="secondary-button" disabled>
          {miniPlatform === "wechat" ? "微信支付" : "抖音支付"}（暂未开通）
        </Button>
        <Text className="list-meta">小程序内支付暂未开放。</Text>
      </View>
    </View>
  );
}
