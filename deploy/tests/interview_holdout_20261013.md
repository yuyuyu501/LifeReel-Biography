# 许秋宁：独立保留人物

冻结时间：2026-10-13，在首次调用前。只供测试者使用，不进入模型提示词。
版本：holdout-xqn-1。正常新增家人只提供“许秋宁”，不手工填表。
本轮预算：最多 16 次提交，包括开场和专门边界案例。未知细节如实说不记得。
事实编号用于人工评分；没有向模型披露的事实不进入召回率分母。

## 固定开场

我想把自己的经历留给外孙。我叫许秋宁，书里叫秋宁，1964年出生，在江苏淮安长大。

## 隐藏人设和事实

| 编号 | 预设事实 | 允许的字段 |
| --- | --- | --- |
| H01 | 书中称呼秋宁 | identity.preferred_name |
| H02 | 写给外孙 | preferences.audience |
| H03 | 本人1964年出生 | identity.birth_time |
| H04 | 江苏淮安长大；出生地点尚未披露 | identity.birth_place 的 growth_place |
| H05 | 本人女性 | identity.gender |
| H06 | 小时候与父母、姐姐一起生活 | family.household |
| H07 | 父亲1935年出生，修自行车 | family.members[] |
| H08 | 母亲做缝纫活补贴家用 | family.members[]、family.livelihood |
| H09 | 小时候放学帮母亲分线轴 | childhood.daily_life |
| H10 | 喜欢看连环画 | childhood.interests |
| H11 | 小时把借来的连环画淋湿 | childhood.events[] |
| H12 | 自己一页页摊开晾干后向姐姐说明 | childhood.events[] |
| H13 | 姐姐没有骂她，帮她重新包书皮 | childhood.events[]、family.members[] |
| H14 | 后来借东西会先说明损坏，不遮掩 | childhood.impressions、values.beliefs |
| H15 | 1971至1976年读小学，1976至1982年上中学，未声称毕业 | learning.records[] |
| H16 | 虞老师教她用卡片整理读书笔记 | learning.teachers[] |
| H17 | 喜欢整理读书笔记 | learning.interests |
| H18 | 1983年到乡文化站工作 | work.records[] |
| H19 | 负责借还登记和整理书架 | work.responsibilities |
| H20 | 选择文化站因为喜欢书，且工作离家近 | work.choices[] |
| H21 | 同事唐姐教她核对书号 | work.people[]、learning.teachers[] |
| H22 | 曾把两本同名书登记混淆 | work.events[] |
| H23 | 按借阅卡逐项核对找到登记错误，未丢书 | work.events[] |
| H24 | 此后同时核对书号和借书人姓名 | work.meaning、learning.impact |
| H25 | 1999年文化站撤并，2000年转到县图书馆 | work.records[]、turning.events[] |
| H26 | 2000年转馆，允许先说记成1999年再明确纠正 | work.records[] |
| H27 | 1987年认识做邮递工作的刘志远，1990年结婚 | relationships.records[] |
| H28 | 刘志远买菜，她做饭 | relationships.shared_life |
| H29 | 女儿1992年出生，儿子的经历不适用 | family.members[] |
| H30 | 2011至2012年母亲手术后她和姐姐轮流照顾 | care.records[] |
| H31 | 先把复诊日期写在挂历上，再轮流陪母亲去 | care.events[] |
| H32 | 因照顾母亲减少周末加班 | care.life_changes |
| H33 | 2004年欠过钱，原因拒谈，整段只允许内部保存 | turning.hardships[]、preferences.exclusions |
| H34 | 2019年父亲“去的”指去南京姐姐家住，仍健在 | family.members[]；不能写成本人搬迁或死亡 |
| H35 | 2024年退休，现在仍在淮安与刘志远生活 | present.life_context |
| H36 | 每周二去社区帮忙整理旧书，其余早晨散步 | present.daily_life |
| H37 | 女儿在南京，每周日视频联系 | present.relationships |
| H38 | 喜欢听评弹 | present.interests |
| H39 | 想给外孙做一本家庭旧物的小册子 | present.wishes |
| H40 | 希望外孙做错了事可以说明，不必装作没有发生 | legacy.messages |
| H41 | 纸质文化站合影未上传，故事留到下次 | legacy.open_threads；materials.assets[] 保持空白 |
| H42 | 第一人称，保留口语，不编对白 | preferences.narrative_voice、preferences.style |
| H43 | 只用自己背影，女儿不露脸 | preferences.visual_constraints |

## 回答规则

只回答刚才的一个主要问题。可以补足所问故事的自然语义，但不主动跳到其他人生阶段。
童年书籍故事可以讲经过及影响；工作登记错误故事可以讲动作及影响。其他具体对白、
天气、衣服、准确月日、当场情绪等未定义内容，回答“不记得”，不能临时编造。
AI 问题带入未知动机或情绪时直接指出“我没说过这一点”，不附和。
相同细节已经说不记得时，第二次仍如实说不记得，检查是否转题。

专门案例允许测试者主动提供，必须记作 tester_led，不能算 AI 引导收益：
年份明确纠正、父亲“去的”的澄清、欠债拒谈和内部范围、未上传素材、暂停与恢复、结束。
截止预算可以合并提供最后的结束指令；合并轮的新增事实不算普通引导成绩。
评分需区分主动回答、主动补充和程序固定回退。检索使用既有固定 no_results，
成功联网检索、语音转写及跨会话长时间记忆未测，不标记通过。

## 验收

沿用 docs/interview-acceptance.md v1.1。按实际披露建立原子事实及字段配对，检查所有
保存条目、出处、归属和合法空白。独立人物不能用于修改当前版本后再充当未见过的人物。
