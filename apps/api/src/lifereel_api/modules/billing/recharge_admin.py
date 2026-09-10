"""Offline payment reconciliation. Never expose this as a customer API."""

import argparse
import json
from uuid import UUID

from sqlalchemy import select

from lifereel_api import main as _main  # noqa: F401 - register all database models
from lifereel_api.core.database import SessionLocal
from lifereel_api.core.errors import ApiError
from lifereel_api.modules.billing.models import RechargeOrder
from lifereel_api.modules.billing.recharge import review, serialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="List the latest 50 pending or submitted payment intents")
    for name in ["confirm", "reject"]:
        command = actions.add_parser(name)
        command.add_argument("--order-id", type=UUID, required=True)
        command.add_argument("--operator", required=True)
        if name == "confirm":
            command.add_argument("--amount-cents", type=int, required=True)
            command.add_argument("--wechat-transaction", required=True)
            command.add_argument(
                "--received",
                action="store_true",
                required=True,
                help="I verified this payment in the recipient's WeChat ledger",
            )
        else:
            command.add_argument("--reason", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.action == "list":
            rows = db.scalars(
                select(RechargeOrder)
                .where(RechargeOrder.status.in_(["pending", "submitted"]))
                .order_by(RechargeOrder.created_at.desc())
                .limit(50)
            )
            print(
                json.dumps(
                    [{**serialize(row), "tenant_id": str(row.tenant_id)} for row in rows],
                    default=str,
                    ensure_ascii=False,
                )
            )
            return
        if not 1 <= len(args.operator.strip()) <= 100:
            parser.error("operator must contain 1-100 characters")
        rejection = args.reason.strip() if args.action == "reject" else None
        if args.action == "reject" and not 1 <= len(rejection) <= 300:
            parser.error("reason must contain 1-300 characters")
        reference = None
        if args.action == "confirm":
            reference = args.wechat_transaction
        try:
            row = review(
                db,
                args.order_id,
                args.operator.strip(),
                reference,
                getattr(args, "amount_cents", None),
                rejection,
            )
            db.commit()
        except ApiError as exc:
            db.rollback()
            parser.exit(1, f"{exc.code}\n")
        print(json.dumps(serialize(row), default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
