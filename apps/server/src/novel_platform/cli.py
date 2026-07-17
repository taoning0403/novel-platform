import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from uuid import UUID

from novel_platform.api.dependencies.storage import get_file_storage
from novel_platform.application.auth.admin_service import AdminService, IssuedRecoveryCredential
from novel_platform.application.auth.audit_service import AuditService
from novel_platform.application.auth.migration_service import AuthMigrationService
from novel_platform.application.errors import ApplicationError
from novel_platform.config import get_settings
from novel_platform.infrastructure.database.session import session_factory


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="novel-platform", description="安全的站点认证与迁移操作命令"
    )
    groups = root.add_subparsers(dest="group", required=True)

    admin = groups.add_parser("admin", help="管理员初始化、恢复与紧急控制")
    admin_commands = admin.add_subparsers(dest="admin_command", required=True)
    init = admin_commands.add_parser("init", help="初始化唯一管理员并签发一次性凭证")
    init.add_argument("--display-name", required=True)
    recovery = admin_commands.add_parser("recovery", help="管理员恢复")
    recovery_commands = recovery.add_subparsers(dest="recovery_command", required=True)
    recovery_commands.add_parser("create", help="签发一次性恢复凭证")
    credentials = admin_commands.add_parser("credentials", help="管理员 Passkey")
    credential_commands = credentials.add_subparsers(dest="credentials_command", required=True)
    credential_commands.add_parser("reset", help="撤销 Passkey/Session 并进入恢复流程")
    sessions = admin_commands.add_parser("sessions", help="管理员会话")
    session_commands = sessions.add_subparsers(dest="sessions_command", required=True)
    session_commands.add_parser("revoke-all", help="撤销全部管理员会话")
    admin_commands.add_parser("status", help="显示脱敏管理员状态")
    admin_commands.add_parser("lock", help="紧急锁定管理员入口")
    admin_commands.add_parser("unlock", help="解除管理员紧急锁定")

    auth = groups.add_parser("auth", help="认证迁移与审计")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    migration = auth_commands.add_parser("migration", help="v0.4.0 到 v0.5.0 转换")
    migration_commands = migration.add_subparsers(dest="migration_command", required=True)
    migration_commands.add_parser("preflight", help="只读迁移预检")
    migration_commands.add_parser("audit", help="脱敏核对数据库与 library volume")
    convert = migration_commands.add_parser("convert", help="执行显式所有权与身份转换")
    convert.add_argument("--target-admin-id", type=UUID)
    convert.add_argument("--map-admin-to-reader", action="append", type=UUID, default=[])
    audit = auth_commands.add_parser("audit", help="安全审计保留")
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    audit_commands.add_parser("cleanup", help="按站点保留天数清理旧事件")
    return root


def print_issued(issued: IssuedRecoveryCredential) -> None:
    print("一次性管理员凭证(仅显示本次,请立即安全保存):")
    print(issued.credential)
    print(f"用途: {issued.purpose.value}")
    print(f"到期: {issued.expires_at.isoformat()}")
    print("请勿写入环境文件、shell history、报告或聊天记录。")


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    async with session_factory() as session:
        if args.group == "admin":
            service = AdminService(session, settings)
            if args.admin_command == "init":
                print_issued(await service.initialize(args.display_name))
            elif args.admin_command == "recovery":
                print_issued(await service.create_recovery())
            elif args.admin_command == "credentials":
                print_issued(await service.reset_credentials())
            elif args.admin_command == "sessions":
                count = await service.revoke_all_sessions()
                print(json.dumps({"revoked_sessions": count}, ensure_ascii=False))
            elif args.admin_command == "status":
                print(json.dumps(asdict(await service.status()), ensure_ascii=False, indent=2))
            elif args.admin_command == "lock":
                await service.lock()
                print(json.dumps({"locked": True}))
            elif args.admin_command == "unlock":
                await service.unlock()
                print(json.dumps({"locked": False}))
            return
        if args.auth_command == "migration":
            migration = AuthMigrationService(session)
            if args.migration_command == "preflight":
                preflight_report = await migration.preflight()
                print(json.dumps(preflight_report.to_dict(), ensure_ascii=False, indent=2))
            elif args.migration_command == "audit":
                storage = get_file_storage()
                storage.initialize()
                integrity_report = await migration.integrity_audit(storage)
                if not integrity_report.consistent:
                    raise ApplicationError(
                        "library_integrity_failed",
                        "数据库与 library volume 一致性审计失败。",
                        details=integrity_report.to_dict(),
                    )
                print(json.dumps(integrity_report.to_dict(), ensure_ascii=False, indent=2))
            else:
                target = await migration.convert(
                    target_admin_id=args.target_admin_id,
                    map_admin_to_reader_ids=set(args.map_admin_to_reader),
                )
                print(json.dumps({"target_admin_id": str(target), "converted": True}))
            return
        if args.auth_command == "audit":
            deleted = await AuditService(session).cleanup()
            print(json.dumps({"deleted_events": deleted}, ensure_ascii=False))


def main() -> None:
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
    except ApplicationError as exc:
        payload = {"error": exc.code, "message": exc.message, "details": exc.details}
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
