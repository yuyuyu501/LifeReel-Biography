import json

TEMPLATE_VERSION = "life-profile-2026-10-08-v1"
RULE_VERSION = "life-readiness-v2"
SECTIONS = json.loads(r"""[
  {
    "title": "基本信息与讲述范围",
    "key": "A"
  },
  {
    "title": "家庭与成长背景",
    "key": "B"
  },
  {
    "title": "童年与少年经历",
    "key": "C"
  },
  {
    "title": "学习与成长",
    "key": "D"
  },
  {
    "title": "工作、事业与生计",
    "key": "E"
  },
  {
    "title": "伴侣与亲密关系",
    "key": "F"
  },
  {
    "title": "养育、照顾与家庭责任",
    "key": "G"
  },
  {
    "title": "转折、困难与重要选择",
    "key": "H"
  },
  {
    "title": "成就、遗憾与价值观",
    "key": "I"
  },
  {
    "title": "目前的生活",
    "key": "J"
  },
  {
    "title": "寄语与未讲完的故事",
    "key": "K"
  },
  {
    "title": "素材与创作偏好",
    "key": "L"
  }
]""")
FIELDS = json.loads(r"""[
  {
    "key": "identity.preferred_name",
    "priority": "基础，优先复用人物称呼",
    "label": "书中称呼",
    "question": "书里希望怎么称呼这位人物？可以用化名。",
    "section": "A",
    "kind": "短文本"
  },
  {
    "key": "contributors.records[]",
    "priority": "基础，可自动带入；代述时澄清",
    "label": "讲述者及与人物的关系",
    "question": "这些是您的亲身经历，还是您替家人讲述？",
    "section": "A",
    "kind": "角色与关系列表"
  },
  {
    "key": "scope.coverage",
    "priority": "基础，默认全人生；写书前确认",
    "label": "想记录的人生范围",
    "question": "您想先记录整个经历，还是从一段最想讲的故事开始？",
    "section": "A",
    "kind": "全人生/时期/主题"
  },
  {
    "key": "identity.birth_time",
    "priority": "可选",
    "label": "出生时间",
    "question": "出生年代大概是什么时候？不清楚可以留空。",
    "section": "A",
    "kind": "时间原话与精度"
  },
  {
    "key": "identity.birth_place",
    "priority": "建议，可只到城市/乡村",
    "label": "出生地与成长地",
    "question": "最早住在哪里？后来有搬过家吗？",
    "section": "A",
    "kind": "地点列表"
  },
  {
    "key": "identity.gender",
    "priority": "可选，不默认追问",
    "label": "自述性别",
    "question": "仅在用户主动提供或明确要求写入时记录。",
    "section": "A",
    "kind": "可空短文本"
  },
  {
    "key": "identity.aliases",
    "priority": "可选",
    "label": "曾用名、亲友称呼",
    "question": "家里人有没有一个经常叫您的称呼？",
    "section": "A",
    "kind": "文本列表"
  },
  {
    "key": "family.origin",
    "priority": "建议",
    "label": "家乡与家庭来历",
    "question": "您对家乡最深的印象是什么？",
    "section": "B",
    "kind": "短文本/地点"
  },
  {
    "key": "family.household",
    "priority": "建议",
    "label": "一起长大的人",
    "question": "小时候主要和哪些人一起生活？",
    "section": "B",
    "kind": "关系记录列表"
  },
  {
    "key": "family.members[]",
    "priority": "建议，可多条",
    "label": "重要家人",
    "question": "这位家人在您的成长中起了什么作用？",
    "section": "B",
    "kind": "人物关系记录"
  },
  {
    "key": "family.home_environment",
    "priority": "建议",
    "label": "居住与生活条件",
    "question": "那时候家里是什么样的生活？",
    "section": "B",
    "kind": "叙述"
  },
  {
    "key": "family.livelihood",
    "priority": "可选",
    "label": "家庭生计",
    "question": "当时家里主要靠什么维持生活？",
    "section": "B",
    "kind": "叙述"
  },
  {
    "key": "family.traditions",
    "priority": "可选",
    "label": "家规、习惯和家庭记忆",
    "question": "有没有一种家里的习惯，您到现在还记得？",
    "section": "B",
    "kind": "叙述/事件列表"
  },
  {
    "key": "childhood.daily_life",
    "priority": "建议",
    "label": "日常生活",
    "question": "小时候平常一天怎么过？",
    "section": "C",
    "kind": "叙述"
  },
  {
    "key": "childhood.events[]",
    "priority": "建议，可多条",
    "label": "难忘的童年经历",
    "question": "哪件小时候的事，到现在仍记得经过？",
    "section": "C",
    "kind": "经历记录"
  },
  {
    "key": "childhood.friends[]",
    "priority": "可选",
    "label": "朋友与伙伴",
    "question": "有没有一个一起长大的伙伴？",
    "section": "C",
    "kind": "人物/经历记录"
  },
  {
    "key": "childhood.interests",
    "priority": "可选",
    "label": "游戏、爱好和愿望",
    "question": "那时最喜欢做什么，曾经想成为什么人？",
    "section": "C",
    "kind": "文本/叙述"
  },
  {
    "key": "childhood.challenges[]",
    "priority": "条件，自愿讲述",
    "label": "困难和应对",
    "question": "如果愿意说，那时遇到过什么难事，您怎样应对？",
    "section": "C",
    "kind": "经历记录"
  },
  {
    "key": "childhood.impressions",
    "priority": "可选",
    "label": "对那段生活的感受",
    "question": "现在回看，您怎样理解那段日子？",
    "section": "C",
    "kind": "自述"
  },
  {
    "key": "learning.records[]",
    "priority": "建议，允许未上学",
    "label": "上学、自学或学手艺",
    "question": "您在哪些地方学过东西？学校、自学、学手艺都可以。",
    "section": "D",
    "kind": "学习记录"
  },
  {
    "key": "learning.teachers[]",
    "priority": "可选",
    "label": "影响自己的人",
    "question": "有没有人教会您一件重要的事？",
    "section": "D",
    "kind": "人物/经历记录"
  },
  {
    "key": "learning.interests",
    "priority": "可选",
    "label": "喜欢的知识或技能",
    "question": "哪种东西让您愿意主动去学？",
    "section": "D",
    "kind": "文本列表"
  },
  {
    "key": "learning.choices[]",
    "priority": "条件，不默认学历路径",
    "label": "继续、转学、停学等选择",
    "question": "学习过程中有没有一次重要选择？",
    "section": "D",
    "kind": "经历记录"
  },
  {
    "key": "learning.impact",
    "priority": "建议",
    "label": "学习对后来的影响",
    "question": "这段学习后来怎样帮到了您？",
    "section": "D",
    "kind": "自述"
  },
  {
    "key": "work.records[]",
    "priority": "建议，允许不同劳动形式",
    "label": "做过的工作、经营或家务劳动",
    "question": "您平时靠什么生活，做过哪些工作或长期劳动？",
    "section": "E",
    "kind": "工作记录"
  },
  {
    "key": "work.responsibilities",
    "priority": "建议",
    "label": "具体负责什么",
    "question": "那份工作一天里具体要做哪些事？",
    "section": "E",
    "kind": "叙述，关联工作记录"
  },
  {
    "key": "work.events[]",
    "priority": "建议，可多条",
    "label": "工作中难忘的经历",
    "question": "有哪一次工作经历让您至今印象很深？",
    "section": "E",
    "kind": "经历记录"
  },
  {
    "key": "work.choices[]",
    "priority": "条件",
    "label": "入行、转行或创业选择",
    "question": "当时为什么做这个选择，又付出了什么？",
    "section": "E",
    "kind": "经历记录"
  },
  {
    "key": "work.people[]",
    "priority": "可选",
    "label": "同事、搭档和帮助者",
    "question": "有没有一位一起做事的人，对您很重要？",
    "section": "E",
    "kind": "人物/经历记录"
  },
  {
    "key": "work.meaning",
    "priority": "建议",
    "label": "收获、代价与看法",
    "question": "这段工作给您的生活带来了什么变化？",
    "section": "E",
    "kind": "自述"
  },
  {
    "key": "relationships.applicability",
    "priority": "条件，不假定已婚",
    "label": "是否愿意记录这一类",
    "question": "这部分想记录吗？也可以跳过。",
    "section": "F",
    "kind": "适用/不适用/跳过"
  },
  {
    "key": "relationships.records[]",
    "priority": "条件，适用且愿意时",
    "label": "重要关系及相识",
    "question": "您愿意讲讲一段重要关系是怎样开始的吗？",
    "section": "F",
    "kind": "关系记录"
  },
  {
    "key": "relationships.shared_life",
    "priority": "可选",
    "label": "相处与共同生活",
    "question": "两个人日常怎样相处？",
    "section": "F",
    "kind": "叙述，关联关系"
  },
  {
    "key": "relationships.events[]",
    "priority": "可选",
    "label": "关系中的重要经历",
    "question": "有没有一件共同经历改变了你们？",
    "section": "F",
    "kind": "经历记录"
  },
  {
    "key": "relationships.reflections",
    "priority": "可选",
    "label": "对关系的理解",
    "question": "现在回看，您最看重这段关系的什么？",
    "section": "F",
    "kind": "自述"
  },
  {
    "key": "care.applicability",
    "priority": "条件，不假定有子女",
    "label": "是否有想讲的照顾经历",
    "question": "有没有一段照顾别人或被照顾的经历想记录？",
    "section": "G",
    "kind": "适用/不适用/跳过"
  },
  {
    "key": "care.records[]",
    "priority": "条件，可多条",
    "label": "照顾谁、由谁照顾",
    "question": "那段时间您主要照顾谁，或者谁照顾您？",
    "section": "G",
    "kind": "关系与时期"
  },
  {
    "key": "care.events[]",
    "priority": "条件",
    "label": "养育或照顾中的故事",
    "question": "有没有一件小事，最能说明那段生活？",
    "section": "G",
    "kind": "经历记录"
  },
  {
    "key": "care.life_changes",
    "priority": "可选",
    "label": "对生活的改变",
    "question": "这份责任怎样改变了您的生活？",
    "section": "G",
    "kind": "自述"
  },
  {
    "key": "care.messages",
    "priority": "可选",
    "label": "想对家人说的话",
    "question": "如果愿意，最想对他们说什么？",
    "section": "G",
    "kind": "原话/自述"
  },
  {
    "key": "turning.events[]",
    "priority": "建议，可多条",
    "label": "人生的重要转折",
    "question": "哪件事让您的生活走向了不同的方向？",
    "section": "H",
    "kind": "经历记录"
  },
  {
    "key": "turning.moves[]",
    "priority": "条件",
    "label": "搬迁、离乡与新的生活",
    "question": "如果有搬迁，为什么离开，又怎样适应新地方？",
    "section": "H",
    "kind": "经历记录"
  },
  {
    "key": "turning.hardships[]",
    "priority": "可选，不主动深挖创伤",
    "label": "愿意记录的困难",
    "question": "有什么困难是您愿意留下记录的？",
    "section": "H",
    "kind": "经历记录"
  },
  {
    "key": "turning.decisions[]",
    "priority": "建议",
    "label": "选择与当时的考虑",
    "question": "当时有哪些选择，您为什么选了这条路？",
    "section": "H",
    "kind": "经历/自述"
  },
  {
    "key": "turning.support",
    "priority": "可选",
    "label": "帮助与应对方法",
    "question": "是什么帮助您走过了那段日子？",
    "section": "H",
    "kind": "人物/自述"
  },
  {
    "key": "turning.impact",
    "priority": "建议",
    "label": "后来的变化",
    "question": "这件事后来对您有什么影响？",
    "section": "H",
    "kind": "自述"
  },
  {
    "key": "values.proud_events[]",
    "priority": "建议，不局限奖项",
    "label": "最珍惜或自豪的事",
    "question": "哪件事让您觉得，这一生值得？",
    "section": "I",
    "kind": "经历记录"
  },
  {
    "key": "values.regrets",
    "priority": "可选",
    "label": "愿意说的遗憾",
    "question": "有没有一件希望当时做得不同的事？不愿说可跳过。",
    "section": "I",
    "kind": "自述"
  },
  {
    "key": "values.beliefs",
    "priority": "建议",
    "label": "坚持与原则",
    "question": "有什么事情，是您一直坚持的？",
    "section": "I",
    "kind": "自述"
  },
  {
    "key": "values.changes",
    "priority": "可选",
    "label": "观念如何变化",
    "question": "哪个看法是经历一些事情后才改变的？",
    "section": "I",
    "kind": "叙述"
  },
  {
    "key": "values.self_description",
    "priority": "可选",
    "label": "如何看待自己",
    "question": "如果用自己的话介绍这一生，您会怎么说？",
    "section": "I",
    "kind": "原话/自述"
  },
  {
    "key": "present.life_context",
    "priority": "建议，不假定退休",
    "label": "最近一个人生阶段",
    "question": "最近的生活主要是什么样子？",
    "section": "J",
    "kind": "叙述/大致地点"
  },
  {
    "key": "present.daily_life",
    "priority": "可选",
    "label": "日常安排",
    "question": "现在平常一天怎么过？",
    "section": "J",
    "kind": "叙述"
  },
  {
    "key": "present.interests",
    "priority": "可选",
    "label": "当前爱好",
    "question": "最近喜欢做什么？",
    "section": "J",
    "kind": "文本/叙述"
  },
  {
    "key": "present.relationships",
    "priority": "可选",
    "label": "目前的重要联系",
    "question": "现在经常陪伴或联系的是哪些人？",
    "section": "J",
    "kind": "人物关系"
  },
  {
    "key": "present.wishes",
    "priority": "可选",
    "label": "心愿和想做的事",
    "question": "还有什么想尝试或完成的事？",
    "section": "J",
    "kind": "自述"
  },
  {
    "key": "legacy.messages",
    "priority": "建议",
    "label": "留给读者或家人的话",
    "question": "希望读这本书的人记住什么？",
    "section": "K",
    "kind": "原话/自述"
  },
  {
    "key": "legacy.lessons",
    "priority": "可选",
    "label": "经验与建议",
    "question": "有什么经验想留给后来的人？",
    "section": "K",
    "kind": "自述"
  },
  {
    "key": "legacy.events[]",
    "priority": "可选，可随时添加",
    "label": "还想讲的故事",
    "question": "还有哪件事是表格里没提到、但您特别想留下的？",
    "section": "K",
    "kind": "经历记录"
  },
  {
    "key": "legacy.open_threads",
    "priority": "系统整理，用户可编辑",
    "label": "下次继续的话题",
    "question": "这件事我们下次从哪里继续？",
    "section": "K",
    "kind": "话题列表"
  },
  {
    "key": "materials.assets[]",
    "priority": "可选，可关联经历",
    "label": "照片、录音、文字资料",
    "question": "有没有一份已经上传的资料能帮助说明这件事？",
    "section": "L",
    "kind": "现有资产引用"
  },
  {
    "key": "materials.captions",
    "priority": "条件，有素材时",
    "label": "素材中的人物、时间和故事",
    "question": "您知道这张照片是什么时候、有哪些人吗？",
    "section": "L",
    "kind": "说明，关联资产"
  },
  {
    "key": "preferences.audience",
    "priority": "写书前确认，采访可预填",
    "label": "写给谁看",
    "question": "这本书主要想写给谁看？",
    "section": "L",
    "kind": "文本/选项"
  },
  {
    "key": "preferences.narrative_voice",
    "priority": "写书前确认",
    "label": "第一/第三人称",
    "question": "想用“我”的口吻，还是由旁人来讲述？",
    "section": "L",
    "kind": "选项"
  },
  {
    "key": "preferences.style",
    "priority": "可选",
    "label": "语言与写作风格",
    "question": "希望尽量保留口语，还是稍作整理？",
    "section": "L",
    "kind": "文本/选项"
  },
  {
    "key": "preferences.exclusions",
    "priority": "可选，随时修改",
    "label": "不写进作品的内容",
    "question": "哪些内容只想保留资料，不写进书或视频？",
    "section": "L",
    "kind": "条目范围/说明"
  },
  {
    "key": "preferences.visual_constraints",
    "priority": "可选，制作时再确认",
    "label": "将来的影像要求",
    "question": "如有影像计划，可以记录哪些人物能露脸、哪些只能用背影。",
    "section": "L",
    "kind": "结构化要求/原话"
  }
]""")
FIELD_MAP = {item["key"]: item for item in FIELDS}
