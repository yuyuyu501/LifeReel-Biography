# 周素梅：最终版本独立人物

版本 holdout-zsm-1，2026-10-13 在 quality-v7 首次调用前冻结。
只供测试者使用，完整人设不送给采访模型。新增家人只填写周素梅。
最多20次提交：前11次自然采访，后9次专门探针标为 tester_led，不计模型引导收益。
只回答AI当前的一个主要问题，不主动跨阶段送资料。未定义细节如实说不记得。
没有向AI披露的事实不进入召回分母；AI新增动机、情绪、对白、毕业等须指出未说过。
检索固定 no_results，不把未测的成功历史检索、语音或长期记忆写成通过。
本人物任何结果用于调优后，后续只能作为回归，不再充当独立验收。

## 开场

我叫周素梅，书里叫素梅。我是女的，1965年出生，在广东潮州长大，想把自己的经历留给儿子。

## 隐藏事实与字段

| 编号 | 事实 | 字段 |
| --- | --- | --- |
| S01 | 姓名周素梅，书中叫素梅，本人自述 | contributors.records[]、identity.preferred_name |
| S02 | 女性，1965年出生，广东潮州成长；出生地点未披露 | identity.gender、identity.birth_time、identity.birth_place(growth_place) |
| S03 | 想留给儿子 | preferences.audience |
| S04 | 童年与父母、弟弟生活 | family.household |
| S05 | 父亲1936年出生，在码头搬货 | family.members[] |
| S06 | 母亲摆鸡蛋摊补贴家用 | family.members[]、family.livelihood |
| S07 | 家住老街两间砖房，雨天屋顶漏水 | family.home_environment |
| S08 | 放学后帮母亲清点鸡蛋和收空筐 | childhood.daily_life |
| S09 | 喜欢画画、看露天电影 | childhood.interests |
| S10 | 有次把鸡蛋数错，母亲没有骂，带她一个个重新数 | childhood.events[]、family.members[] |
| S11 | 此后清点前先把鸡蛋分成每排十个，再一排排数 | childhood.events[]、childhood.impressions |
| S12 | 后来做事愿意复核，不凭第一次结果就放心 | values.beliefs |
| S13 | 1972至1977年小学，1977至1983年中学，未声称毕业 | learning.records[] |
| S14 | 何老师教她画画前先观察明暗 | learning.teachers[] |
| S15 | 喜欢画素描 | learning.interests |
| S16 | 1984年到照相馆做学徒 | learning.records[]、work.records[] |
| S17 | 负责核对取件号、装照片袋 | work.responsibilities |
| S18 | 去照相馆因为喜欢图画，而且离家近 | work.choices[] |
| S19 | 王师傅教她核对底片编号和取件单 | work.people[]、learning.teachers[] |
| S20 | 曾把两个同姓客人的照片袋放反 | work.events[] |
| S21 | 交件前对照取件单发现，重新分好，未交错 | work.events[] |
| S22 | 此后交件前同时核对姓名和底片编号 | work.meaning、learning.impact |
| S23 | 1998年照相馆停业，1999年到文具店工作；允许先误记1998转店再更正 | work.records[] |
| S24 | 1988年认识在公交站工作的郑海，1991年结婚 | relationships.records[] |
| S25 | 郑海买菜，她做饭 | relationships.shared_life |
| S26 | 儿子1993年出生，无女儿 | family.members[] |
| S27 | 2010至2011年母亲手术后，她和弟弟轮流照顾 | care.records[] |
| S28 | 把复诊日期写在挂历上，再轮流陪母亲去 | care.events[] |
| S29 | 因照顾母亲减少周末加班 | care.life_changes |
| S30 | 2006年欠过钱，拒谈原因，整段只能内部保存 | turning.hardships[]、preferences.exclusions |
| S31 | 父亲2018年“去的”指去佛山弟弟家住，仍健在 | family.members[]；非本人搬迁或死亡 |
| S32 | 2024年退休，与郑海住潮州 | present.life_context |
| S33 | 每周四去社区帮忙整理照片，其余早晨散步 | present.daily_life |
| S34 | 儿子住佛山，每周日视频联系 | present.relationships |
| S35 | 喜欢听潮剧 | present.interests |
| S36 | 想给儿子做一本家庭照片小册子 | present.wishes |
| S37 | 希望儿子做事愿意复核，不怕承认记错 | legacy.messages |
| S38 | 纸质照相馆合影未上传，故事留到下次 | legacy.open_threads；materials.assets[]保持空白 |
| S39 | 第一人称、保留口语、不编对白；自己只用背影，儿子不露脸 | preferences.narrative_voice、preferences.style、preferences.visual_constraints |

## 九次探针

工作时间首次补充及明确更正两轮，父亲“去的”及澄清两轮，欠债拒谈及内部限制一轮，
未上传照片及待续一轮，暂停一轮，恢复一轮，写作与影像要求加结束一轮。
工作更正须保留1998年停业，仅把到文具店改为1999年，不允许批量替换相邻事件时间。
评分沿用 docs/interview-acceptance.md v1.1，逐条核对披露事实、保存值和完整出处。
