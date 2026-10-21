import { useEffect, useState } from "react";
import { Button, Image, Input, Text, View } from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type { Person } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { PageFrame } from "../../shared/PageFrame";
import { Icon, type IconName } from "../../shared/Icon";

const entries: {
  page: string;
  title: string;
  detail: string;
  icon: IconName;
}[] = [
  {
    page: "profile",
    title: "人生资料",
    detail: "经历与人物关系",
    icon: "profile",
  },
  {
    page: "books",
    title: "人生之书",
    detail: "目录与已保存书稿",
    icon: "book",
  },
  {
    page: "production",
    title: "人生影像",
    detail: "剧本、分镜与视频",
    icon: "film",
  },
  {
    page: "memory",
    title: "记忆档案",
    detail: "事实与时间线",
    icon: "archive",
  },
];

export default function HomePage() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [newPersonName, setNewPersonName] = useState("");
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function load() {
    setError("");
    setLoading(true);
    Promise.all([miniApi.me(), miniApi.persons()])
      .then(([, people]) => {
        setPersons(people);
        const requested = getCurrentInstance().router?.params?.subjectId;
        setSelectedPersonId(
          (prior) =>
            people.find((p) => p.id === (prior || requested))?.id ||
            people[0]?.id ||
            "",
        );
      })
      .catch((e) => setError(e instanceof Error ? e.message : "家人加载失败"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);
  const selected = persons.find((p) => p.id === selectedPersonId);
  function open(page: string) {
    if (!selected || adding) return;
    void Taro.navigateTo({
      url: `/pages/${page}/index?subjectId=${encodeURIComponent(selected.id)}`,
    });
  }
  async function createPerson() {
    if (!newPersonName.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const person = await miniApi.createPerson({
        display_name: newPersonName.trim(),
      });
      setPersons((items) => [...items, person]);
      setSelectedPersonId(person.id);
      setNewPersonName("");
      setAdding(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "家人创建失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <PageFrame
      title="我的家人"
      subtitle="把熟悉的人，认真记下来。"
      active="home"
      subjectId={selectedPersonId}
      locked={adding}
      className="home-page"
      action={
        <Button
          className="icon-button"
          aria-label={adding ? "关闭新增家人" : "新增家人"}
          disabled={busy}
          onClick={() => setAdding(!adding)}
        >
          <Icon name="plus" />
        </Button>
      }
    >
      {error && (
        <View className="error-row">
          <Text className="error">{error}</Text>
          <Button className="text-button" onClick={load}>
            重试
          </Button>
        </View>
      )}
      {adding && (
        <View className="surface person-form">
          <Text className="section-title">新增家人</Text>
          <Text className="label">姓名或称呼</Text>
          <Input
            className="input"
            maxlength={80}
            value={newPersonName}
            placeholder="例如：爸爸、林秀兰"
            onInput={(e) => setNewPersonName(e.detail.value)}
          />
          <View className="action-row">
            <Button
              className="primary-button"
              loading={busy}
              disabled={busy || !newPersonName.trim()}
              onClick={createPerson}
            >
              添加家人
            </Button>
            <Button
              className="secondary-button"
              disabled={busy}
              onClick={() => setAdding(false)}
            >
              取消
            </Button>
          </View>
        </View>
      )}
      {loading ? (
        <Text className="empty">正在读取家人档案……</Text>
      ) : persons.length ? (
        <View className="person-list">
          {persons.map((person) => (
            <Button
              className={`person-row ${person.id === selectedPersonId ? "is-selected" : ""}`}
              key={person.id}
              onClick={() => setSelectedPersonId(person.id)}
            >
              <Text className="person-avatar">
                {(person.preferred_name || person.display_name).slice(0, 1)}
              </Text>
              <View className="person-copy">
                <Text className="list-title">
                  {person.preferred_name || person.display_name}
                </Text>
                <Text className="list-meta">
                  {[
                    person.relation_to_owner,
                    person.birth_year
                      ? `${person.birth_year} 年生`
                      : "出生年份待补充",
                    person.birthplace,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </Text>
              </View>
              <View
                className={`selection-mark ${person.id === selectedPersonId ? "is-selected" : ""}`}
              >
                {person.id === selectedPersonId && (
                  <Icon name="check" tone="white" />
                )}
              </View>
            </Button>
          ))}
        </View>
      ) : (
        <View className="empty-state">
          <Image
            className="empty-illustration"
            src={require("../../assets/interview.png")}
            mode="aspectFit"
          />
          <Text className="section-title">第一份家人档案</Text>
          <Button className="primary-button" onClick={() => setAdding(true)}>
            <Icon name="plus" tone="white" />
            添加家人
          </Button>
        </View>
      )}
      {selected && (
        <>
          <View className="next-interview">
            <View className="next-interview-copy">
              <Text className="eyebrow">下一段故事</Text>
              <Text className="section-title">
                和{selected.preferred_name || selected.display_name}聊一聊
              </Text>
              <Button
                className="primary-button"
                onClick={() => open("interview")}
              >
                <Icon name="mic" tone="white" />
                开始或继续采访
                <Icon name="arrow" tone="white" />
              </Button>
            </View>
            <Image
              className="interview-art"
              src={require("../../assets/interview.png")}
              mode="aspectFit"
            />
          </View>
          <View className="section-heading">
            <Text className="section-title">家人档案</Text>
            <Text className="caption">
              {selected.preferred_name || selected.display_name}
            </Text>
          </View>
          <View className="archive-grid">
            {entries.map((entry) => (
              <Button
                className="archive-entry"
                key={entry.page}
                onClick={() => open(entry.page)}
              >
                <Icon name={entry.icon} />
                <Text className="list-title">{entry.title}</Text>
                <Text className="list-meta">{entry.detail}</Text>
                <View className="entry-arrow">
                  <Icon name="arrow" tone="muted" />
                </View>
              </Button>
            ))}
          </View>
        </>
      )}
      <View className="account-row">
        <View className="privacy-label">
          <Icon name="lock" tone="muted" />
          <Text>仅在家庭空间内保存</Text>
        </View>
        <Button
          className="text-button"
          disabled={adding || busy}
          onClick={() => {
            miniApi.clearAuth();
            void Taro.reLaunch({ url: "/pages/login/index" });
          }}
        >
          <Icon name="logout" tone="muted" />
          退出
        </Button>
      </View>
    </PageFrame>
  );
}
