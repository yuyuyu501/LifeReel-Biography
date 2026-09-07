from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.config import get_settings
from lifereel_api.modules.auth.models import TenantMembership, UserAccount
from lifereel_api.modules.auth.security import hash_password
from lifereel_api.modules.identity.models import Tenant
from lifereel_api.modules.interview.models import Chapter

DEFAULT_CHAPTERS = [
    (1, "我是谁", "从名字、出生和现在的生活开始认识您。", ["您希望我们怎样称呼您？"]),
    (2, "我的来处", "家乡、父母和家族，是许多故事的起点。", ["您出生的地方是什么样的？"]),
    (3, "童年岁月", "那些最早的玩伴、物件和生活气味。", ["小时候最常和谁一起玩？"]),
    (4, "求学时代", "学校、老师、同学和第一次形成的理想。", ["您还记得第一位老师吗？"]),
    (5, "工作与理想", "谋生、选择、挫折和值得骄傲的事。", ["您的第一份工作是什么？"]),
    (6, "爱情与婚姻", "相遇、陪伴与共同生活。", ["您和伴侣第一次见面是什么情景？"]),
    (7, "为人亲长", "成为父母、长辈和家庭支柱的经历。", ["第一次成为父母时是什么感受？"]),
    (8, "坎坷与选择", "生命中的困难、改变方向和重新站起来。", ["哪次选择最改变您的人生？"]),
    (9, "高光与遗憾", "最闪亮的时刻与仍然放在心里的事。", ["哪件事让您最为自己骄傲？"]),
    (10, "现在的日子", "此刻的生活、牵挂和仍想完成的愿望。", ["现在一天里最喜欢的时刻是什么？"]),
    (11, "寄语", "留给家人、晚辈和未来的话。", ["最想让晚辈记住的一句话是什么？"]),
]


def seed_foundation(db: Session) -> None:
    settings = get_settings()
    tenant = db.get(Tenant, settings.default_tenant_id)
    if tenant is None:
        tenant = Tenant(id=settings.default_tenant_id, name="Development Family", slug="dev-family")
        db.add(tenant)
        db.flush()

    has_chapter = db.scalar(select(Chapter.id).where(Chapter.tenant_id == tenant.id).limit(1))
    if not has_chapter:
        for order, title, description, questions in DEFAULT_CHAPTERS:
            db.add(
                Chapter(
                    tenant_id=tenant.id,
                    order_index=order,
                    title=title,
                    description=description,
                    opening_questions=questions,
                    is_system=True,
                )
            )
    owner_email = settings.bootstrap_owner_email
    owner_password = settings.bootstrap_owner_password
    if settings.app_env == "development" and not owner_email:
        owner_email = "demo@lifereel.local"
        owner_password = "LifeReelDemo2026!"
    if owner_email and owner_password:
        owner = db.scalar(select(UserAccount).where(UserAccount.email == owner_email.lower()))
        if owner is None:
            owner = UserAccount(
                email=owner_email.lower(),
                display_name=settings.bootstrap_owner_name,
                password_hash=hash_password(owner_password),
            )
            db.add(owner)
            db.flush()
            db.add(
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=owner.id,
                    role="owner",
                )
            )
    db.commit()
