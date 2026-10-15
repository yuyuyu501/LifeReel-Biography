"""Frozen new combinations; target facts never enter provider inputs."""

VERSION = "grounding-retrieval-cases-20261014-v1"


def atom(entity, predicate, value, field, sources, status="reported"):
    return {
        "entity": entity,
        "predicate": predicate,
        "value": value,
        "field": field,
        "sources": sources,
        "status": status,
    }


def item(key, answers, targets, **extra):
    return {"id": key, "answers": answers, "targets": targets, **extra}


def distant(first, last):
    return [first, *[f"这段闲话第{i}次，先放一放。" for i in range(1, 12)], last]


FAMILY = "family.members[]"
WORK = "work.records[]"
RELATIONS = "present.relationships"
CASES = [
    item(
        "G01",
        ["父亲每周三给我打电话。女儿每周一给母亲打电话，不是母亲给女儿打。"],
        [
            atom("father", "call_recipient", "本人", RELATIONS, [1]),
            atom("father", "contact_frequency", "每周三", RELATIONS, [1]),
            atom("daughter", "call_recipient", "母亲", RELATIONS, [1]),
            atom("daughter", "contact_frequency", "每周一", RELATIONS, [1]),
        ],
    ),
    item(
        "G02",
        distant("我2004年欠过债。", "欠债那件事的原因我不想讲，整个经历只供内部，不要写进作品。"),
        [
            atom("self", "debt_cause", "未披露", "turning.hardships[]", [1, 13], "declined"),
            atom("self", "use_scope", "整个欠债经历仅内部使用", "turning.hardships[]", [13]),
            atom(
                "self",
                "preferences_exclusions",
                "欠债经历不用于作品",
                "preferences.exclusions",
                [13],
            ),
        ],
        internal=True,
    ),
    item(
        "G03",
        distant("我每周开店六天，晚上给母亲打电话。", "开店现在每周两天，电话的时间和对象都没变。"),
        [
            atom("self", "work_days_per_week", "每周两天", "present.daily_life", [13]),
            atom("self", "call_time", "晚上", "present.daily_life", [1, 13]),
            atom("self", "call_recipient", "母亲", "present.daily_life", [1, 13]),
        ],
    ),
    item(
        "G04",
        ["2001年我调入市图书馆工作，负责修补旧书。"],
        [
            atom("self", "employment_start", "2001年", WORK, [1]),
            atom("self", "workplace", "市图书馆", WORK, [1]),
            atom("self", "event_action", "修补旧书", WORK, [1]),
        ],
    ),
    item(
        "G05",
        ["女儿2017年搬到宣城。我不知道她现在还住不住那里。"],
        [
            atom("daughter", "moved_to", "宣城", FAMILY, [1]),
            atom("daughter", "move_year", "2017年", FAMILY, [1]),
            atom("daughter", "resides_in", "未确认现在住址", RELATIONS, [1], "unknown"),
        ],
        forbidden=["女儿现在住宣城"],
    ),
    item(
        "G06",
        distant(
            "我1992年进过织布厂，离职经过还没讲。",
            "织布厂2007年停产，不代表我2007年才离开，我没有说一直在那里工作。",
        ),
        [
            atom("org:织布厂", "closure_year", "2007年", WORK, [13]),
            atom("self", "continuous_employment", "未断言连续任职", WORK, [1, 13], "unknown"),
        ],
        forbidden=["2007年离职", "不是2007年离职"],
    ),
    item("G07", ["父亲和叔叔都来过。他1943年出生，我没说清楚是谁。"], [], requires_pending=True),
    item(
        "G08",
        ["我有一张1992年的纸质全家福，还没有上传。今天先聊到这里。"],
        [
            atom("self", "material_status", "1992年纸质全家福未上传", "legacy.open_threads", [1]),
        ],
        action="close",
        forbidden=["materials.assets[]"],
    ),
]

# The interview model sees only answers selected in response to its actual questions.
# No full persona or topic catalog is sent to Lite or Sol.
PERSONA = {
    "name": "许静岚",
    "opening": "书里叫我许静岚。我1965年出生，在宜昌长大。年轻时在照相馆工作，后来做过修表。",
    "topics": [
        {
            "id": "childhood",
            "cues": ["小时候", "童年", "长大", "宜昌", "儿时"],
            "answers": [
                "小时候我常和姐姐沿江散步，姐姐叫许静华。",
                "那时我喜欢看过往船只，不过具体船名记不清了。",
            ],
        },
        {
            "id": "photo",
            "cues": ["照相馆", "照相", "照片", "摄影", "冲洗", "底片"],
            "answers": [
                "1984年我进了江城照相馆，做底片冲洗。",
                "梁师傅教我控制冲洗温度，他是我的照相馆师傅。",
                "有一回我把水温弄高了，梁师傅让我重新做。从那以后我总先量水温。",
            ],
        },
        {
            "id": "watch",
            "cues": ["修表", "钟表", "手表", "转行", "后来", "手艺", "技能"],
            "answers": [
                "1993年我离开照相馆，去学修表。",
                "教我修表的是姨父，不是梁师傅。姨父叫陈立平。",
                "修表让我学会先检查再动手，我现在做事也保留这个习惯。",
            ],
        },
        {
            "id": "family",
            "cues": ["家人", "家庭", "女儿", "孩子", "母亲", "父亲", "电话"],
            "answers": [
                "我女儿2018年搬去湖州，现在仍住在那里。",
                "每周日是女儿给我打电话，我母亲偶尔也在旁边听。",
            ],
        },
        {
            "id": "present",
            "cues": ["现在", "日常", "平时", "生活", "退休", "爱好", "愿望"],
            "answers": [
                "现在我每周在社区修表两天，周二和周五。",
                "我想把先检查再动手的习惯留给女儿，她做什么职业我先不讲。",
            ],
        },
    ],
    "boundary_answer": "1996年我欠过债，原因不想谈。这整段只供内部使用，不要写进作品。",
    "resume_answer": "现在继续，刚才欠债的原因还是不谈。我们换个话题。",
    "correction_answer": (
        "更正一下，江城照相馆的入职年份是1985年，不是1984年，"
        "梁师傅教我冲洗没有变。"
    ),
    "close_answer": "我没有上传任何照片，今天先聊到这里。",
    "policy": (
        "Answer only a selected asked topic; unknown details remain unknown. "
        "Control probes are marked tester initiated."
    ),
}
