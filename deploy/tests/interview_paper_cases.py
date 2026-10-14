"""Frozen synthetic disclosures; gold is never sent to a tested provider."""

VERSION = "paper-methods-20261014-v1"


def fact(subject, predicate, value, field, sources, status="reported"):
    return {
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "field": field,
        "status": status,
        "sources": sources,
    }


def case(key, category, answers, gold, *, abstain=False, long=False):
    return {
        "id": key,
        "category": category,
        "sources": [{"id": f"U{i + 1}", "text": text} for i, text in enumerate(answers)],
        "gold": gold,
        "must_abstain": abstain,
        "long": long,
    }


FAMILY = "family.members[]"
WORK = "work.records[]"
DAILY = "present.daily_life"
RELATIONS = "present.relationships"

CASES = [
    case(
        "C01",
        "coreference",
        [
            "我1970年出生。我父亲是2008年去的。",
            "去的是长沙，在我弟弟家住，不是去世了。父亲现在还活着，1938年出生的是他，不是我。",
        ],
        [
            fact("父亲", "moved_to", "长沙", FAMILY, ["U1", "U2"]),
            fact("父亲", "move_year", "2008", FAMILY, ["U1", "U2"]),
            fact("父亲", "host", "弟弟", FAMILY, ["U1", "U2"]),
            fact("父亲", "alive", "yes", FAMILY, ["U2"]),
            fact("父亲", "birth_year", "1938", FAMILY, ["U2"]),
        ],
    ),
    case(
        "C02",
        "coreference",
        [
            "我1969年出生，姐姐比我大三岁。妈妈2011年过去了。",
            "是搬去桂林，住我姐姐那儿。妈妈1941年出生，现在还在，刚才不是说她过世。",
        ],
        [
            fact("母亲", "moved_to", "桂林", FAMILY, ["U1", "U2"]),
            fact("母亲", "move_year", "2011", FAMILY, ["U1", "U2"]),
            fact("母亲", "host", "姐姐", FAMILY, ["U1", "U2"]),
            fact("母亲", "birth_year", "1941", FAMILY, ["U2"]),
            fact("母亲", "alive", "yes", FAMILY, ["U2"]),
        ],
    ),
    case(
        "C03",
        "coreference",
        [
            "我爸1939年生，我叔叔1945年生。爸2009年搬到了衡阳。",
            "他住在叔叔家，叔叔本人一直没搬。",
        ],
        [
            fact("父亲", "host", "叔叔", FAMILY, ["U1", "U2"]),
            fact("叔叔", "move_denied", "yes", FAMILY, ["U2"]),
        ],
    ),
    case(
        "C04",
        "ambiguity",
        [
            "父亲和弟弟都在家。",
            "他2015年去了南京，后来就在那儿住下。",
        ],
        [],
        abstain=True,
    ),
    case(
        "C05",
        "roles",
        [
            "我一直住湘潭。父亲2008年搬到长沙，住弟弟家；弟弟2012年搬去了武汉。",
        ],
        [
            fact("本人", "resides_in", "湘潭", "present.life_context", ["U1"]),
            fact("父亲", "moved_to", "长沙", FAMILY, ["U1"]),
            fact("父亲", "move_year", "2008", FAMILY, ["U1"]),
            fact("父亲", "host", "弟弟", FAMILY, ["U1"]),
            fact("弟弟", "moved_to", "武汉", FAMILY, ["U1"]),
            fact("弟弟", "move_year", "2012", FAMILY, ["U1"]),
        ],
    ),
    case(
        "C06",
        "roles",
        [
            "2006年母亲去南昌照顾姐姐。姐姐没有搬家，是母亲搬过去住的。",
        ],
        [
            fact("母亲", "moved_to", "南昌", FAMILY, ["U1"]),
            fact("母亲", "move_year", "2006", FAMILY, ["U1"]),
            fact("母亲", "event_action", "照顾姐姐", FAMILY, ["U1"]),
            fact("姐姐", "move_denied", "yes", FAMILY, ["U1"]),
        ],
    ),
    case(
        "C07",
        "correction",
        [
            "我1986年进修理厂，2001年离开。",
            "离开那年说错了，是2002年，不是2001年。",
        ],
        [fact("本人", "employment_end", "2002", WORK, ["U1", "U2"])],
    ),
    case(
        "C08",
        "correction",
        [
            "我1999年离开车间，2000年转到图书馆。",
            "车间是1999年撤并的，我2000年才转去图书馆。这两个年份别改成一样。",
        ],
        [
            fact("车间", "closure_year", "1999", WORK, ["U2"]),
            fact("本人", "employment_start", "2000", WORK, ["U2"]),
            fact("本人", "workplace", "图书馆", WORK, ["U2"]),
        ],
    ),
    case(
        "C09",
        "correction",
        [
            "妈妈1940年出生。爸爸1937年出生。",
            "更正一下，1942年出生的是妈妈，爸爸的年份不变。",
        ],
        [fact("母亲", "birth_year", "1942", FAMILY, ["U2"])],
    ),
    case(
        "C10",
        "correction",
        [
            "儿子住长沙，女儿住湘潭。",
            "刚才把他们的城市说反了，儿子在湘潭，女儿在长沙。",
        ],
        [
            fact("儿子", "resides_in", "湘潭", RELATIONS, ["U2"]),
            fact("女儿", "resides_in", "长沙", RELATIONS, ["U2"]),
        ],
    ),
    case(
        "C11",
        "omission",
        [
            "我每周开店四天，早晨散步，晚上给父亲打电话。儿子住长沙，女儿住湘潭，孩子们每周末和我联系。",
        ],
        [
            fact("本人", "work_days_per_week", "4", DAILY, ["U1"]),
            fact("本人", "walk_time", "早晨", DAILY, ["U1"]),
            fact("本人", "call_time", "晚上", DAILY, ["U1"]),
            fact("本人", "call_recipient", "父亲", DAILY, ["U1"]),
            fact("儿子", "resides_in", "长沙", RELATIONS, ["U1"]),
            fact("女儿", "resides_in", "湘潭", RELATIONS, ["U1"]),
            fact("子女", "contact_frequency", "每周末", RELATIONS, ["U1"]),
        ],
    ),
    case(
        "C12",
        "ellipsis",
        [
            "我每天早晨散步，晚上给父亲打电话。",
            "散步、打电话都照旧。",
        ],
        [
            fact("本人", "walk_time", "早晨", DAILY, ["U1", "U2"]),
            fact("本人", "call_time", "晚上", DAILY, ["U1", "U2"]),
            fact("本人", "call_recipient", "父亲", DAILY, ["U1", "U2"]),
        ],
    ),
    case(
        "C13",
        "roles",
        [
            "儿子每周日给我打电话，不是我给他打。女儿每周六给父亲打电话。",
        ],
        [
            fact("儿子", "call_recipient", "本人", RELATIONS, ["U1"]),
            fact("儿子", "contact_frequency", "每周日", RELATIONS, ["U1"]),
            fact("女儿", "call_recipient", "父亲", RELATIONS, ["U1"]),
            fact("女儿", "contact_frequency", "每周六", RELATIONS, ["U1"]),
        ],
    ),
    case(
        "C14",
        "presupposition",
        [
            "1997年我欠了钱。原因不想讲，整段欠债经历只留在内部，不放进作品。",
        ],
        [
            fact("本人", "debt_year", "1997", "turning.hardships[]", ["U1"]),
            fact("本人", "debt_cause", "未披露", "turning.hardships[]", ["U1"], "declined"),
            fact("本人", "use_scope", "欠债经历仅内部使用", "turning.hardships[]", ["U1"]),
        ],
    ),
    case(
        "C15",
        "uncertainty",
        [
            "父亲大概1940年出生，也可能1941年，我记不准。他现在还活着。",
        ],
        [
            fact("父亲", "birth_year", "1940或1941", FAMILY, ["U1"], "uncertain"),
            fact("父亲", "alive", "yes", FAMILY, ["U1"]),
        ],
    ),
    case(
        "C16",
        "material",
        [
            "1992年的纸质结婚照还没上传，下次再给你。摆摊第一天的故事留到下次说。",
        ],
        [
            fact(
                "本人", "material_status", "1992年纸质结婚照未上传", "legacy.open_threads", ["U1"]
            ),
            fact(
                "本人",
                "deferred_topic",
                "摆摊第一天的故事",
                "legacy.open_threads",
                ["U1"],
                "deferred",
            ),
        ],
    ),
    case(
        "C17",
        "presupposition",
        [
            "1986年我进过修理厂，2002年厂子关了，中间的工作经历还没讲。",
        ],
        [
            fact("本人", "employment_start", "1986", WORK, ["U1"]),
            fact("本人", "workplace", "修理厂", WORK, ["U1"]),
            fact("修理厂", "closure_year", "2002", WORK, ["U1"]),
            fact(
                "本人",
                "deferred_topic",
                "中间的工作经历",
                "legacy.open_threads",
                ["U1"],
                "deferred",
            ),
        ],
    ),
    case(
        "C18",
        "ambiguity",
        [
            "妈妈和姨妈都在这里。",
            "她1943年出生，现在还活着。",
        ],
        [],
        abstain=True,
    ),
]


def long_case(key, category, opening, ending, gold, *, abstain=False):
    # Fixed distractors contain other people and dates; no hidden answer is inserted.
    distractors = [
        "邻居提过2015年南京的雨，我没有去过南京。",
        "弟弟有个朋友住长沙，我不清楚这个朋友的出生年份。",
        "我小时候喜欢听广播，但具体节目名字记不清。",
        "姐姐昨天买了菜，买了什么我没有问。",
        "我现在喜欢种花，不清楚花的品种。",
        "女儿讲过她同事的趣事，同事的姓名就不说了。",
        "父亲会编篮子，母亲以前种过菜。",
        "照片还在抽屉里，这轮先不上传。",
    ] * 4
    return case(key, category, [opening, *distractors, ending], gold, abstain=abstain, long=True)


LAST = "U34"
CASES += [
    long_case(
        "C19",
        "long_coreference",
        "父亲2008年搬去长沙，住弟弟家。",
        "我爸那次搬家的年份说错了，是2009年，地方和住谁家没变。",
        [
            fact("父亲", "move_year", "2009", FAMILY, ["U1", LAST]),
            fact("父亲", "moved_to", "长沙", FAMILY, ["U1", LAST]),
            fact("父亲", "host", "弟弟", FAMILY, ["U1", LAST]),
        ],
    ),
    long_case(
        "C20",
        "long_coreference",
        "母亲2011年搬到桂林，住姐姐家。",
        "妈妈搬家那事，更正为2013年，城市和住处照旧。",
        [
            fact("母亲", "move_year", "2013", FAMILY, ["U1", LAST]),
            fact("母亲", "moved_to", "桂林", FAMILY, ["U1", LAST]),
            fact("母亲", "host", "姐姐", FAMILY, ["U1", LAST]),
        ],
    ),
    long_case(
        "C21",
        "long_ellipsis",
        "我每天早晨散步，晚上给父亲打电话。",
        "我说的散步和打电话，都还是原来的时间和对象。",
        [
            fact("本人", "walk_time", "早晨", DAILY, ["U1", LAST]),
            fact("本人", "call_time", "晚上", DAILY, ["U1", LAST]),
            fact("本人", "call_recipient", "父亲", DAILY, ["U1", LAST]),
        ],
    ),
    long_case(
        "C22",
        "long_update",
        "儿子在杭州住，女儿在合肥住。",
        "女儿搬到芜湖了，儿子仍在我开始说的那个城市。",
        [
            fact("女儿", "resides_in", "芜湖", RELATIONS, [LAST]),
            fact("儿子", "resides_in", "杭州", RELATIONS, ["U1", LAST]),
        ],
    ),
    long_case(
        "C23",
        "long_correction",
        "我1988年进印刷厂，2003年离开。",
        "印刷厂离开的年份改成2004年，进厂年份不变。",
        [
            fact("本人", "employment_end", "2004", WORK, ["U1", LAST]),
            fact("本人", "employment_start", "1988", WORK, ["U1", LAST]),
        ],
    ),
    long_case(
        "C24",
        "long_boundary",
        "2001年我欠过钱，原因不说，整段仅内部使用。",
        "最早说的欠债那段，年份更正为2000年，使用限制照旧。",
        [
            fact("本人", "debt_year", "2000", "turning.hardships[]", ["U1", LAST]),
            fact("本人", "use_scope", "欠债经历仅内部使用", "turning.hardships[]", ["U1", LAST]),
        ],
    ),
    long_case(
        "C25",
        "long_material",
        "1995年纸质合影没有上传，准备以后给你。",
        "开头那张合影现在仍未上传，年份更正为1996年。",
        [
            fact(
                "本人",
                "material_status",
                "1996年纸质合影未上传",
                "legacy.open_threads",
                ["U1", LAST],
            ),
        ],
    ),
    long_case(
        "C26",
        "long_coreference",
        "父亲1939年出生，母亲1944年出生。",
        "妈妈出生年份改成1945年，爸爸的不用改。",
        [
            fact("母亲", "birth_year", "1945", FAMILY, [LAST]),
        ],
    ),
    long_case(
        "C27",
        "long_update",
        "我每周开店五天，早晨散步。",
        "每周开店改为三天，散步还是原来那个时间。",
        [
            fact("本人", "work_days_per_week", "3", DAILY, [LAST]),
            fact("本人", "walk_time", "早晨", DAILY, ["U1", LAST]),
        ],
    ),
    long_case(
        "C28",
        "long_presupposition",
        "我1985年进过机修厂，没讲后来工作。",
        "机修厂2000年停产。我没有说过自己一直在厂里工作到停产。",
        [
            fact("机修厂", "closure_year", "2000", WORK, [LAST]),
            fact("本人", "continuous_employment", "未断言", WORK, [LAST], "unknown"),
        ],
    ),
    long_case(
        "C29",
        "long_ambiguity",
        "父亲和弟弟都说想搬家，没说谁最后搬了。",
        "他后来2017年搬去了苏州。",
        [],
        abstain=True,
    ),
    long_case(
        "C30",
        "long_roles",
        "儿子每周五给我打电话，女儿每周日给母亲打电话。",
        "儿子的电话改到每周六，对象不变；女儿的都照旧。",
        [
            fact("儿子", "contact_frequency", "每周六", RELATIONS, [LAST]),
            fact("儿子", "call_recipient", "本人", RELATIONS, ["U1", LAST]),
            fact("女儿", "contact_frequency", "每周日", RELATIONS, ["U1", LAST]),
            fact("女儿", "call_recipient", "母亲", RELATIONS, ["U1", LAST]),
        ],
    ),
]
