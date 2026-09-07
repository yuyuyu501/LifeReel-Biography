from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from lifereel_api.modules.interview.models import Chapter


class ChapterPromptProfile(TypedDict):
    title: str
    keywords: list[str]
    required_topics: list[str]
    excluded_topics: list[str]
    interview_goal: str
    script_goal: str


_PROFILES: dict[int, ChapterPromptProfile] = {
    1: {
        "title": "我是谁",
        "keywords": ["姓名", "称呼", "出生", "家乡", "现在的生活", "性格", "身份认同"],
        "required_topics": ["希望如何称呼", "出生时间与地点", "当前生活状态", "如何理解自己"],
        "excluded_topics": ["完整童年事件", "求学经历细节", "婚姻过程", "工作履历"],
        "interview_goal": "建立人物的基本身份、当下生活与自我认知",
        "script_goal": "形成简洁、真实、有辨识度的第一人称人物自我介绍",
    },
    2: {
        "title": "我的来处",
        "keywords": ["家乡", "祖籍", "父母", "家族", "故土", "家庭氛围", "迁徙"],
        "required_topics": ["家乡面貌", "父母与家庭", "家族记忆", "来处带来的影响"],
        "excluded_topics": ["完整童年故事", "求学细节", "职业履历", "婚姻过程"],
        "interview_goal": "还原人物的地域、家庭与家族根源",
        "script_goal": "写成一章关于故土与家族来处的第一人称叙述",
    },
    3: {
        "title": "童年岁月",
        "keywords": ["童年", "玩伴", "家人", "游戏", "物件", "气味", "生活环境"],
        "required_topics": ["童年生活环境", "常见玩伴", "难忘小事", "童年感受"],
        "excluded_topics": ["成年工作", "婚姻生活", "晚年愿望", "完整求学经历"],
        "interview_goal": "唤起可感知、可复述的童年生活片段",
        "script_goal": "用具体场景写成一章有生活质感的童年回忆",
    },
    4: {
        "title": "求学时代",
        "keywords": ["学校", "老师", "同学", "课程", "考试", "理想", "校园生活"],
        "required_topics": ["学校与年代", "重要老师或同学", "难忘经历", "当时的理想"],
        "excluded_topics": ["完整童年生活", "职业生涯", "婚姻过程", "晚年生活"],
        "interview_goal": "梳理学习经历及其对人物成长的影响",
        "script_goal": "写成一章围绕校园、师友与理想形成的求学记忆",
    },
    5: {
        "title": "工作与理想",
        "keywords": ["第一份工作", "职业", "选择", "同事", "技能", "挫折", "成就", "理想"],
        "required_topics": ["职业起点", "关键选择", "工作挑战", "骄傲或收获"],
        "excluded_topics": ["童年游戏", "完整求学生活", "婚姻过程", "晚年寄语"],
        "interview_goal": "理解人物如何谋生、选择并实现自己的价值",
        "script_goal": "写成一章有转折、有行动也有反思的职业经历",
    },
    6: {
        "title": "爱情与婚姻",
        "keywords": ["相遇", "恋爱", "伴侣", "婚礼", "共同生活", "陪伴", "磨合"],
        "required_topics": ["如何相遇", "决定相伴的原因", "共同生活片段", "对陪伴的理解"],
        "excluded_topics": ["完整工作履历", "童年生活", "子女成长全程", "泛化人生寄语"],
        "interview_goal": "记录伴侣之间的相遇、选择与长期陪伴",
        "script_goal": "写成一章克制而具体的爱情与婚姻叙述",
    },
    7: {
        "title": "为人亲长",
        "keywords": ["父母", "子女", "长辈", "养育", "责任", "家庭", "陪伴", "传承"],
        "required_topics": ["身份转变", "养育或照顾经历", "家庭责任", "希望传承的东西"],
        "excluded_topics": ["恋爱过程", "完整职业履历", "童年游戏", "泛化高光事件"],
        "interview_goal": "呈现人物成为父母、长辈或家庭支柱的过程",
        "script_goal": "写成一章关于责任、照顾与代际传承的家庭叙述",
    },
    8: {
        "title": "坎坷与选择",
        "keywords": ["困难", "失去", "转折", "选择", "坚持", "改变", "重新开始"],
        "required_topics": ["困难发生的背景", "关键选择", "如何度过", "留下的影响"],
        "excluded_topics": ["无关日常琐事", "完整爱情经历", "泛化职业介绍", "晚年寄语"],
        "interview_goal": "在尊重隐私的前提下理解困难、选择与韧性",
        "script_goal": "写成一章不过度煽情、突出选择与改变的生命转折",
    },
    9: {
        "title": "高光与遗憾",
        "keywords": ["骄傲", "成就", "高光", "遗憾", "错过", "释怀", "评价"],
        "required_topics": ["最骄傲的时刻", "为何重要", "仍在心里的遗憾", "现在如何看待"],
        "excluded_topics": ["完整职业履历", "完整婚姻过程", "童年日常", "泛化当前生活"],
        "interview_goal": "帮助人物回望成就与遗憾，并表达当下评价",
        "script_goal": "写成一章有对照、有分寸的高光与遗憾回望",
    },
    10: {
        "title": "现在的日子",
        "keywords": ["日常", "作息", "家人", "爱好", "牵挂", "健康", "愿望", "当下"],
        "required_topics": ["一天的生活", "喜欢的事", "当前牵挂", "仍想完成的愿望"],
        "excluded_topics": ["完整童年往事", "完整职业履历", "婚姻全过程", "家族源流"],
        "interview_goal": "记录人物此刻真实、具体的生活状态与愿望",
        "script_goal": "写成一章安静具体的当下生活切片",
    },
    11: {
        "title": "寄语",
        "keywords": ["家人", "晚辈", "感谢", "叮嘱", "价值观", "祝愿", "传承"],
        "required_topics": ["最想感谢的人", "希望晚辈记住什么", "重要的人生原则", "未来祝愿"],
        "excluded_topics": ["重新展开完整生平", "详细职业履历", "详细婚姻过程", "无关生活流水账"],
        "interview_goal": "凝练人物真正想留给家人与未来的话",
        "script_goal": "写成一章真诚、简洁、可直接对家人说出的寄语",
    },
}


def get_chapter_prompt_profile(chapter: Chapter | None) -> ChapterPromptProfile:
    if chapter is not None and chapter.order_index in _PROFILES:
        profile = _PROFILES[chapter.order_index]
        if profile["title"] == chapter.title:
            return profile
    if chapter is not None:
        for profile in _PROFILES.values():
            if profile["title"] == chapter.title:
                return profile
    title = chapter.title if chapter is not None else "自由采访"
    description = chapter.description if chapter is not None else None
    return {
        "title": title,
        "keywords": [title, "时间", "地点", "人物", "经过", "感受", "影响"],
        "required_topics": ["时间与地点", "相关人物", "事情经过", "感受与影响"],
        "excluded_topics": [],
        "interview_goal": description or "围绕当前主题补充真实、可核验的生命故事",
        "script_goal": f"只围绕“{title}”写成一章连贯的第一人称叙述",
    }

