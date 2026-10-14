# 赵文岚：第二套独立人物

版本 holdout-zwl-1。2026-10-13 在 quality-v5 首次调用前冻结。
只供测试者使用，不送给采访模型。正常新增家人只提供赵文岚，资料表保持初始空白。
最多20次提交。前11次为自然采访，后9次允许专门边界探针，均记录 tester_led。
未定义的对白、天气、衣服、月日、情绪、毕业和任职结束时间如实回答不知道。
只回答AI当前的一个主要问题，不主动补充其他阶段。AI有未经披露的解释时指出未说过。
仅已向AI披露的事实进入召回分母；未披露的完整人设不能当作模型输入或计分事实。

## 固定开场

我叫赵文岚，书里叫文岚。我是男的，1962年出生，在江西赣州长大，想把自己的经历留给女儿。

## 隐藏事实与允许字段

| 编号 | 事实 | 字段 |
| --- | --- | --- |
| Z01 | 书中称呼文岚，本人自述 | identity.preferred_name、contributors.records[] |
| Z02 | 男性，1962年出生，江西赣州成长，出生地未知 | identity.gender、identity.birth_time、identity.birth_place(growth_place) |
| Z03 | 写给女儿 | preferences.audience |
| Z04 | 小时候与父母、哥哥生活 | family.household |
| Z05 | 父亲1933年出生，开公交车 | family.members[] |
| Z06 | 母亲给人缝衣补贴家用 | family.members[]、family.livelihood |
| Z07 | 小时候放学后帮母亲把布头按大小分好 | childhood.daily_life |
| Z08 | 喜欢收集邮票 | childhood.interests |
| Z09 | 借哥哥一本邮票册，不慎把一页撕破 | childhood.events[] |
| Z10 | 用薄纸补好后向哥哥说明，哥哥没有骂，只教他翻页托住纸角 | childhood.events[]、family.members[] |
| Z11 | 后来借物损坏会主动说明 | childhood.impressions、values.beliefs |
| Z12 | 1969至1974年小学，1974至1980年中学，未声称毕业 | learning.records[] |
| Z13 | 罗老师教他把地图按路口分段记 | learning.teachers[] |
| Z14 | 喜欢看地图、记路线 | learning.interests |
| Z15 | 1981年到县邮电局做投递员 | work.records[] |
| Z16 | 按街道分信，再骑车投递 | work.responsibilities |
| Z17 | 选择投递因为喜欢记路线，且可以在本地工作 | work.choices[] |
| Z18 | 前辈丁师傅教他在出发前核对门牌号 | work.people[]、learning.teachers[] |
| Z19 | 一次把两封同姓收信人的信分错袋 | work.events[] |
| Z20 | 出发前对照地址发现，重新分好，没有投错 | work.events[] |
| Z21 | 此后出发前逐一核对姓名和门牌号 | work.meaning、learning.impact |
| Z22 | 1998年转到局里窗口，允许先说1997再明确更正，未说退休 | work.records[] |
| Z23 | 1986年认识在食品店工作的蒋惠，1989年结婚 | relationships.records[] |
| Z24 | 蒋惠做饭，他洗碗 | relationships.shared_life |
| Z25 | 女儿1991年出生，没有儿子 | family.members[] |
| Z26 | 2012至2013年母亲做手术后，他和哥哥轮流照顾 | care.records[] |
| Z27 | 把复诊日期写在挂历上再轮流陪母亲去 | care.events[] |
| Z28 | 因照顾母亲减少周末加班 | care.life_changes |
| Z29 | 2005年欠过钱，拒谈原因，整段只内部保存 | turning.hardships[]、preferences.exclusions |
| Z30 | 2020年父亲“去的”指去南昌哥哥家住，仍健在 | family.members[]；不能写成本人搬迁或死亡 |
| Z31 | 2023年退休，现在与蒋惠住赣州 | present.life_context |
| Z32 | 每周三去社区帮忙整理旧报，其余早晨散步 | present.daily_life |
| Z33 | 女儿在南昌，每周六视频联系 | present.relationships |
| Z34 | 喜欢听赣南采茶戏 | present.interests |
| Z35 | 想做一本投递路线小册子 | present.wishes |
| Z36 | 希望女儿做错事可以说明，不必遮掩 | legacy.messages |
| Z37 | 纸质邮电局合影没上传，故事留到下次 | legacy.open_threads；materials.assets[]保持空白 |
| Z38 | 第一人称、保留口语、不编对白；自己只用背影，女儿不露脸 | preferences.narrative_voice、preferences.style、preferences.visual_constraints |

## 边界探针与验收

自然采访11轮后，最多9轮：工作年份首次披露及明确更正共两轮，父亲歧义及澄清共两轮，
欠债拒谈及整段内部使用一轮，未上传材料及待续一轮，暂停一轮，继续一轮，写作偏好与结束一轮。
这些主动补充不计为模型引导收益。自然采访得到的相同事实不重复计数。
使用 docs/interview-acceptance.md v1.1，评分依据为完整原话、保存值和出处，程序固定句不计模型收益。
当前检索夹具为 no_results，成功联网检索、语音转写、长期跨会话记忆仍记未测。
本人物测试完成前不修改被冻结代码。若结果用于修改，后续该人物只能算回归，不能再称独立验收。
