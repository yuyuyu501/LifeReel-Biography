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
  const [editingId, setEditingId] = useState("");
  const [editingName, setEditingName] = useState("");
  const [editingPreferredName, setEditingPreferredName] = useState("");
  const [editingBirthYear, setEditingBirthYear] = useState("");
  const [editingBirthplace, setEditingBirthplace] = useState("");
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
  function startEditing(person: Person) {
    setEditingId(person.id);
    setEditingName(person.display_name);
    setEditingPreferredName(person.preferred_name || "");
    setEditingBirthYear(person.birth_year ? String(person.birth_year) : "");
    setEditingBirthplace(person.birthplace || "");
    setError("");
  }
  function cancelEditing() {
    setEditingId("");
    setEditingName("");
    setEditingPreferredName("");
    setEditingBirthYear("");
    setEditingBirthplace("");
  }
  async function savePerson() {
    if (!editingId || !editingName.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const updated = await miniApi.updatePerson(editingId, {
        display_name: editingName.trim(),
        preferred_name: editingPreferredName.trim() || null,
        birth_year: editingBirthYear ? Number(editingBirthYear) : null,
        birthplace: editingBirthplace.trim() || null,
      });
      setPersons((items) =>
        items.map((item) => (item.id === updated.id ? updated : item)),
      );
      cancelEditing();
    } catch (e) {
      setError(e instanceof Error ? e.message : "人物保存失败");
    } finally {
      setBusy(false);
    }
  }
  async function removePerson(person: Person) {
    const result = await Taro.showModal({
      title: "确认删除家人",
      content: `确定删除「${person.preferred_name || person.display_name}」吗？人物档案、采访记录、书稿和影像记录都会删除。`,
      confirmText: "确认删除",
      confirmColor: "#b54d3c",
    });
    if (!result.confirm || busy) return;
    setBusy(true);
    setError("");
    try {
      await miniApi.deletePerson(person.id);
      const remaining = persons.filter((item) => item.id !== person.id);
      setPersons(remaining);
      if (selectedPersonId === person.id)
        setSelectedPersonId(remaining[0]?.id || "");
      if (editingId === person.id) cancelEditing();
    } catch (e) {
      setError(e instanceof Error ? e.message : "人物删除失败");
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
      tutorial={{
        ready: !loading && !error,
        steps: [
          {
            target: "#guide-home-add",
            title: "先添加一位家人",
            description: "点这个加号，填写姓名或称呼，为要记录的人建立档案。",
          },
          ...(selected
            ? [
                {
                  target: "#guide-home-person",
                  title: "选择这次要记录的人",
                  description:
                    "点选家人后，采访、资料、书稿和影像都会归到这位家人的档案里。",
                },
                {
                  target: "#guide-home-interview",
                  title: "从一次采访开始",
                  description:
                    "点这里进入采访。可以打字，也可以录音，先讲一段最想留下的经历。",
                },
                {
                  target: "#guide-home-profile",
                  title: "核对整理出的人生资料",
                  description:
                    "采访后到这里查看记录；发现遗漏或错误，可以直接补充和修改。",
                },
                {
                  target: "#guide-home-books",
                  title: "把资料写成书稿",
                  description:
                    "资料确认后进入写书，调整目录与选材，再生成或手动编辑正文。",
                },
                {
                  target: "#guide-home-production",
                  title: "最后，把书稿变成影像",
                  description:
                    "先用已保存的书稿生成剧本与分镜，核对后再创建视频任务。",
                },
              ]
            : []),
          {
            target: "#guide-help-home",
            title: "随时回来查看引导",
            description: selected
              ? "每个主要页面都有这个问号按钮。完成或跳过后，引导不会在该页面反复弹出。"
              : "先添加家人，再开始采访、核对资料、写书和制作影像。需要时点这个问号，重新查看当前页面的步骤。",
          },
        ],
      }}
      action={
        <Button
          id="guide-home-add"
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
      {editingId && (
        <View className="surface person-form">
          <Text className="section-title">编辑人物档案</Text>
          <Text className="label">姓名</Text>
          <Input
            className="input"
            maxlength={80}
            value={editingName}
            onInput={(e) => setEditingName(e.detail.value)}
          />
          <Text className="label">希望怎样称呼</Text>
          <Input
            className="input"
            maxlength={80}
            value={editingPreferredName}
            onInput={(e) => setEditingPreferredName(e.detail.value)}
          />
          <View className="form-grid">
            <View>
              <Text className="label">出生年份</Text>
              <Input
                className="input"
                type="number"
                value={editingBirthYear}
                onInput={(e) => setEditingBirthYear(e.detail.value)}
              />
            </View>
            <View>
              <Text className="label">出生地</Text>
              <Input
                className="input"
                value={editingBirthplace}
                onInput={(e) => setEditingBirthplace(e.detail.value)}
              />
            </View>
          </View>
          <View className="action-row">
            <Button
              className="primary-button"
              loading={busy}
              disabled={busy || !editingName.trim()}
              onClick={savePerson}
            >
              保存人物
            </Button>
            <Button
              className="secondary-button"
              disabled={busy}
              onClick={cancelEditing}
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
            <View
              className={`person-row ${person.id === selectedPersonId ? "is-selected" : ""}`}
              id={
                person.id === selectedPersonId ? "guide-home-person" : undefined
              }
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
              <View className="person-actions">
                <Button
                  className="person-action edit-action"
                  aria-label={`编辑${person.display_name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    startEditing(person);
                  }}
                >
                  编辑
                </Button>
                <Button
                  className="person-action delete-action"
                  aria-label={`删除${person.display_name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    void removePerson(person);
                  }}
                >
                  删除
                </Button>
              </View>
            </View>
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
                id="guide-home-interview"
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
                id={`guide-home-${entry.page}`}
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
      </View>
    </PageFrame>
  );
}
