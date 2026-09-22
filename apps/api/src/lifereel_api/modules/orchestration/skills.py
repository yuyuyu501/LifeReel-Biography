"""Application skills shared by text turns and realtime voice.

The host supplies identity, source material and idempotency keys. A model can
request a capability, but cannot select another tenant, invent a source, or
bypass the existing billing and evidence checks.
"""

from sqlalchemy import select

from lifereel_api.modules.memory import service as memory
from lifereel_api.modules.memory.models import MemoryClaim
from lifereel_api.modules.memory.schemas import MemoryCompileRequest
from lifereel_api.modules.script import service as script


class MemorySkill:
    name = "sync_memory"

    @staticmethod
    def compile(db, tenant_id, session_id):
        return memory.compile_memories(
            db, tenant_id, MemoryCompileRequest(interview_session_id=session_id),
        )

    @staticmethod
    def chapter_claims(db, tenant_id, subject_id, chapter_id):
        return list(db.scalars(select(MemoryClaim).where(
            MemoryClaim.tenant_id == tenant_id,
            MemoryClaim.subject_id == subject_id,
            MemoryClaim.chapter_id == chapter_id,
            MemoryClaim.review_status.not_in(["disputed", "private"]),
        ).order_by(MemoryClaim.created_at, MemoryClaim.id)))


class ScriptSkill:
    name = "update_script"

    @staticmethod
    def assess(db, tenant_id, claims, rounds, chapter):
        # Lazy import: orchestration owns durable text-turn checkpoints.
        from lifereel_api.modules.orchestration.service import _assess_chapter

        return _assess_chapter(db, tenant_id, claims, rounds, chapter)

    @staticmethod
    def generate(db, tenant_id, request, *, update_brief):
        return script.generate_draft(db, tenant_id, request, update_brief=update_brief)


def voice_tools():
    """Doubao's flat function schema; all write scope comes from the host.

    Calls join the automatic processing of completed ASR utterances. They never
    submit a second copy of a transcript or cause a second charge.
    """
    return [
        {"type": "function", "name": MemorySkill.name,
         "description": "用户讲述新事实或明确纠正旧事实后，等待后台记忆整理结果。"
                        "只处理服务端已接收的完整用户发言；不得自行补充事实。",
         "parameters": {"type": "object", "properties": {},
                        "required": [], "additionalProperties": False}},
        {"type": "function", "name": ScriptSkill.name,
         "description": "用户要求改稿或当前章节内容充分时，获取后台剧本更新结果。"
                        "只使用当前用户、人物、章节的有效记忆和用户创作要求。"
                        "仅 status=completed 时可以告知更新成功。",
         "parameters": {"type": "object", "properties": {},
                        "required": [], "additionalProperties": False}},
    ]
