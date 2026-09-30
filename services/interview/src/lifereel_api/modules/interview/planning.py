"""Lightweight interview controls and candidate guards, shared with the planner."""

import re
from difflib import SequenceMatcher

from lifereel_api.modules.memory.facts import fact_text


def control(text):
    value = re.sub(r"[\s，。！？,.!?]", "", text or "")
    if re.fullmatch(
        r"(?:我)?(?:今天)?(?:先)?(?:不聊了|不说了|暂停|暂停采访|结束采访|到这里|聊到这里|休息一下)(?:吧|了)?",
        value,
    ):
        return "pause"
    if re.fullmatch(r"(?:这个|这段|这件事)?(?:不想说|不想聊|不愿说|跳过)(?:了|吧)?", value):
        return "skip"
    return "continue"


def normalized(text):
    text = re.sub(r"您|你|请问|能否|可以|能不能|能不|可否|是否|能", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text)


def repeated(question, history):
    candidate = normalized(question)
    if not candidate:
        return True
    return any(
        candidate == normalized(old)
        or (
            min(len(candidate), len(normalized(old))) >= 8
            and SequenceMatcher(None, candidate, normalized(old)).ratio() >= 0.84
        )
        for old in history
    )


def relevant_memories(memories, text, limit=12):
    tokens = set(re.findall(r"[\u4e00-\u9fff]{2}|[a-zA-Z0-9]+", text))
    ranked = sorted(
        enumerate(memories),
        key=lambda pair: (
            sum(word in fact_text(pair[1]) for word in tokens),
            -pair[0],
        ),
        reverse=True,
    )
    return [item for _, item in ranked[:limit]]


def candidates(result):
    values = result.get("candidates")
    if isinstance(values, list) and values:
        return [
            item
            for item in values[:3]
            if isinstance(item, dict) and item.get("already_answered") is not True
        ]
    return [result]


PLANNER_GUIDANCE = (
    "每次只提出一个具体问题。"
    "能写初稿不等于用户已经讲完，不得仅因ready_for_script=true或回答简短而结束采访。"
    "只有用户明确暂停/结束时才收束。用户拒绝某话题则换一个本章内轻松的切入点。"
    "结合用户刚说的具体人、时间、地点、工作或生活动作，追问一个容易回答的细节；"
    "避免反复套用'有什么感受/难忘经历'。不要求最低字数或固定轮数，不每次提为了写剧本。"
    "人名、地名、年份存在歧义时先简短确认，不偷偷纠正、不把推测当事实。"
    "年代、地区背景仅用于设计问题，不能假设用户经历了某事件。"
    "用户通过后续对话明确更正时，以最新明确事实和known_memories为准，不沿旧信息继续询问。有revised_answer时以它为准。不能在script_updated=false时宣称剧本已修改完成。"
    "规划最多三个不同切入点，在同一次返回中逐一判断是否已被回答；只选有新信息价值的。"
    "除next_question和intent外，可以返回candidates数组，每项含next_question、intent、"
    "focus（待补细节）、already_answered（语义上已问过或已有答案则true）。"
    "不要仅改写同一个问题，要检查answered_questions和known_memories已有的答案。"
)
