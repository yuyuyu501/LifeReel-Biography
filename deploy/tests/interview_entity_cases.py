"""New combinations for the entity experiment; never exposed as provider answers."""

from interview_paper_cases import DAILY, FAMILY, RELATIONS, WORK, case, fact, long_case

NEW_CASES = [
    case(
        "N01",
        "new_ellipsis",
        [
            "妈妈1998年过去了，我那时还在老家。",
            "那是去岳阳住弟弟家，不是去世。她1946年出生，现在还活着。",
        ],
        [
            fact("母亲", "moved_to", "岳阳", FAMILY, ["U1", "U2"]),
            fact("母亲", "move_year", "1998", FAMILY, ["U1", "U2"]),
            fact("母亲", "host", "弟弟", FAMILY, ["U1", "U2"]),
            fact("母亲", "birth_year", "1946", FAMILY, ["U2"]),
            fact("母亲", "alive", "yes", FAMILY, ["U2"]),
        ],
    ),
    case(
        "N02",
        "new_actor_correction",
        [
            "刚才讲到父亲搬去九江，我1958年出生。",
            "搬家的人说错了，是我2014年搬去九江，住姐姐家。父亲还活着，他没搬。",
        ],
        [
            fact("本人", "moved_to", "九江", "turning.moves[]", ["U2"]),
            fact("本人", "move_year", "2014", "turning.moves[]", ["U2"]),
            fact("本人", "host", "姐姐", "turning.moves[]", ["U2"]),
            fact("父亲", "alive", "yes", FAMILY, ["U2"]),
            fact("父亲", "move_denied", "yes", FAMILY, ["U2"]),
        ],
    ),
    case(
        "N03",
        "new_mixed_ambiguity",
        [
            "母亲和姨妈都来我这里了。",
            "她1948年出生。还有，我现在每周开店三天。",
        ],
        [fact("本人", "work_days_per_week", "3", DAILY, ["U2"])],
    ),
    case(
        "N04",
        "new_identity_correction",
        [
            "我1967年出生，妈妈1942年出生。",
            "我自己的年份改成1968年，妈妈仍然是1942年。",
        ],
        [
            fact("本人", "birth_year", "1968", "identity.birth_time", ["U2"]),
            fact("母亲", "birth_year", "1942", FAMILY, ["U1", "U2"]),
        ],
    ),
    long_case(
        "N05",
        "new_closure",
        "我1991年进过食品厂，离职经过还没讲。",
        "食品厂2006年停产，不代表我2006年才离开，我没有说一直在那儿工作。",
        [
            fact("食品厂", "closure_year", "2006", WORK, ["U34"]),
            fact("本人", "continuous_employment", "未断言", WORK, ["U34"], "unknown"),
        ],
    ),
    case(
        "N06",
        "new_host_roles",
        ["2010年姨妈搬到宜昌住母亲家。母亲从来没搬去宜昌，是姨妈搬的。"],
        [
            fact("姨妈", "moved_to", "宜昌", FAMILY, ["U1"]),
            fact("姨妈", "move_year", "2010", FAMILY, ["U1"]),
            fact("姨妈", "host", "母亲", FAMILY, ["U1"]),
            fact("母亲", "move_denied", "yes", FAMILY, ["U1"]),
        ],
    ),
    case(
        "N07",
        "new_phone_direction",
        ["父亲每周三给我打电话。女儿每周一给母亲打电话，不是母亲给女儿打。"],
        [
            fact("父亲", "call_recipient", "本人", RELATIONS, ["U1"]),
            fact("父亲", "contact_frequency", "每周三", RELATIONS, ["U1"]),
            fact("女儿", "call_recipient", "母亲", RELATIONS, ["U1"]),
            fact("女儿", "contact_frequency", "每周一", RELATIONS, ["U1"]),
        ],
    ),
    case(
        "N08",
        "new_material_correction",
        [
            "我有一张1989年的纸质全家福，还没上传。",
            "全家福年份记错了，是1990年，仍然没上传，其他照片先不讲。",
        ],
        [
            fact(
                "本人",
                "material_status",
                "1990年纸质全家福未上传",
                "legacy.open_threads",
                ["U1", "U2"],
            ),
        ],
    ),
    case(
        "N09",
        "new_privacy",
        ["2003年我欠过钱，原因不讲。整个欠债经历仅内部使用，不放进作品。"],
        [
            fact("本人", "debt_year", "2003", "turning.hardships[]", ["U1"]),
            fact(
                "本人",
                "debt_cause",
                "未披露",
                "turning.hardships[]",
                ["U1"],
                "declined",
            ),
            fact(
                "本人",
                "use_scope",
                "欠债经历仅内部使用",
                "turning.hardships[]",
                ["U1"],
            ),
        ],
    ),
    long_case(
        "N10",
        "new_keep_update",
        "我每周开店六天，晚上给母亲打电话。",
        "开店现在每周两天，电话的时间和对象都没变。",
        [
            fact("本人", "work_days_per_week", "2", DAILY, ["U34"]),
            fact("本人", "call_time", "晚上", DAILY, ["U1", "U34"]),
            fact("本人", "call_recipient", "母亲", DAILY, ["U1", "U34"]),
        ],
    ),
    case(
        "N11",
        "new_clarification_reply",
        [
            "父亲和弟弟都考虑过搬去扬州。",
            "他2018年搬过去了。",
            "刚才的他是弟弟，不是父亲。地点和年份就是刚说的那个。",
        ],
        [
            fact("弟弟", "moved_to", "扬州", FAMILY, ["U1", "U2", "U3"]),
            fact("弟弟", "move_year", "2018", FAMILY, ["U2", "U3"]),
        ],
    ),
    case(
        "N12",
        "new_true_ambiguity",
        ["父亲和叔叔都来看我。", "他1944年出生，我没有说清楚是谁。"],
        [],
        abstain=True,
    ),
]

for item in NEW_CASES:
    item["requires_pending"] = item["must_abstain"] or item["id"] == "N03"
