from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from uuid import UUID

from sqlalchemy import distinct, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.storage import FileStorage
from novel_platform.domain.auth.models import UserRole, UserStatus
from novel_platform.infrastructure.database.models import (
    AuthSessionModel,
    BookModel,
    BookSeriesModel,
    DeviceModel,
    LibraryImportModel,
    ReaderSettingsModel,
    ReadingProgressModel,
    RefreshTokenModel,
    StoredFileModel,
    UserBookPreferenceModel,
    UserModel,
)
from novel_platform.infrastructure.repositories.auth import AuthRepository
from novel_platform.infrastructure.repositories.site import SiteRepository


@dataclass(frozen=True, slots=True)
class OwnerCounts:
    owner_user_id: str
    books: int
    series: int
    stored_files: int
    library_imports: int


@dataclass(frozen=True, slots=True)
class MigrationPreflight:
    alembic_revision: str
    user_ids: list[str]
    admin_ids: list[str]
    owner_counts: list[OwnerCounts]
    reading_progresses: int
    reader_settings: int
    preferences: int
    active_devices: int
    active_sessions: int
    active_refresh_tokens: int
    requires_target_admin: bool
    requires_admin_mapping: bool

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["owner_counts"] = [asdict(item) for item in self.owner_counts]
        return result


@dataclass(frozen=True, slots=True)
class LibraryIntegrityReport:
    database_permanent_files: int
    physical_permanent_files: int
    referenced_temporary_files: int
    missing_permanent_files: int
    unexpected_permanent_files: int
    permanent_checksum_mismatches: int
    missing_temporary_files: int
    temporary_checksum_mismatches: int

    @property
    def consistent(self) -> bool:
        return not any(
            (
                self.missing_permanent_files,
                self.unexpected_permanent_files,
                self.permanent_checksum_mismatches,
                self.missing_temporary_files,
                self.temporary_checksum_mismatches,
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "consistent": self.consistent}


class AuthMigrationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.site = SiteRepository(session)
        self.auth = AuthRepository(session)

    async def preflight(self) -> MigrationPreflight:
        now = datetime.now(UTC)
        revision = await self.session.scalar(text("SELECT version_num FROM alembic_version"))
        users = list(
            (
                await self.session.scalars(
                    select(UserModel).order_by(UserModel.created_at.asc(), UserModel.id)
                )
            ).all()
        )
        admin_ids = [str(user.id) for user in users if user.role == UserRole.ADMIN]
        owner_ids: set[UUID] = set()
        for model in (BookModel, BookSeriesModel, StoredFileModel, LibraryImportModel):
            owner_column = model.owner_user_id
            owner_ids.update((await self.session.scalars(select(distinct(owner_column)))).all())
        owner_counts: list[OwnerCounts] = []
        for owner_id in sorted(owner_ids, key=str):
            owner_counts.append(
                OwnerCounts(
                    owner_user_id=str(owner_id),
                    books=await self._count(BookModel, BookModel.owner_user_id, owner_id),
                    series=await self._count(
                        BookSeriesModel, BookSeriesModel.owner_user_id, owner_id
                    ),
                    stored_files=await self._count(
                        StoredFileModel, StoredFileModel.owner_user_id, owner_id
                    ),
                    library_imports=await self._count(
                        LibraryImportModel, LibraryImportModel.owner_user_id, owner_id
                    ),
                )
            )
        active_devices = await self.session.scalar(
            select(func.count(DeviceModel.id)).where(DeviceModel.revoked_at.is_(None))
        )
        active_sessions = await self.session.scalar(
            select(func.count(AuthSessionModel.id)).where(
                AuthSessionModel.revoked_at.is_(None), AuthSessionModel.expires_at > now
            )
        )
        active_refresh = await self.session.scalar(
            select(func.count(RefreshTokenModel.id)).where(
                RefreshTokenModel.revoked_at.is_(None),
                RefreshTokenModel.used_at.is_(None),
                RefreshTokenModel.expires_at > now,
            )
        )
        return MigrationPreflight(
            alembic_revision=str(revision),
            user_ids=[str(user.id) for user in users],
            admin_ids=admin_ids,
            owner_counts=owner_counts,
            reading_progresses=await self._total(ReadingProgressModel),
            reader_settings=await self._total(ReaderSettingsModel),
            preferences=await self._total(UserBookPreferenceModel),
            active_devices=int(active_devices or 0),
            active_sessions=int(active_sessions or 0),
            active_refresh_tokens=int(active_refresh or 0),
            requires_target_admin=len(admin_ids) != 1 or len(owner_ids) > 1,
            requires_admin_mapping=len(admin_ids) > 1,
        )

    async def convert(
        self,
        *,
        target_admin_id: UUID | None,
        map_admin_to_reader_ids: set[UUID],
    ) -> UUID:
        report = await self.preflight()
        admins = {UUID(value) for value in report.admin_ids}
        if target_admin_id is None:
            if report.requires_target_admin or len(admins) != 1:
                raise ApplicationError(
                    "target_admin_required",
                    "存在多个管理员或内容所有者，必须显式指定唯一目标管理员。",
                    status_code=HTTPStatus.CONFLICT,
                    details=report.to_dict(),
                )
            target_admin_id = next(iter(admins))
        if target_admin_id not in admins:
            raise ApplicationError(
                "invalid_target_admin",
                "目标身份不是现有管理员。",
                status_code=HTTPStatus.CONFLICT,
            )
        non_target_admins = admins - {target_admin_id}
        if map_admin_to_reader_ids != non_target_admins:
            raise ApplicationError(
                "admin_mapping_required",
                "必须逐一明确把所有非目标管理员映射为阅读者。",
                status_code=HTTPStatus.CONFLICT,
                details={
                    "required_admin_ids": sorted(str(value) for value in non_target_admins),
                    "provided_admin_ids": sorted(str(value) for value in map_admin_to_reader_ids),
                },
            )
        target = await self.session.get(UserModel, target_admin_id)
        if target is None:
            raise ApplicationError("invalid_target_admin", "目标管理员不存在。")
        now = datetime.now(UTC)
        for model in (BookModel, BookSeriesModel, StoredFileModel, LibraryImportModel):
            await self.session.execute(update(model).values(owner_user_id=target_admin_id))
        if non_target_admins:
            await self.session.execute(
                update(UserModel)
                .where(UserModel.id.in_(non_target_admins))
                .values(role=UserRole.MEMBER, updated_at=now)
            )
        target.role = UserRole.ADMIN
        target.status = UserStatus.ACTIVE
        target.updated_at = now
        await self.session.execute(
            update(UserModel).values(password_hash=None, password_changed_at=now, updated_at=now)
        )
        await self.session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await self.session.execute(
            update(AuthSessionModel)
            .where(AuthSessionModel.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason="v050_auth_migration")
        )
        await self.session.execute(
            update(DeviceModel)
            .where(DeviceModel.revoked_at.is_(None))
            .values(revoked_at=now, updated_at=now)
        )
        site = await self.site.get(for_update=True)
        site.library_owner_user_id = target_admin_id
        site.migration_completed_at = now
        site.updated_at = now
        self.auth.audit(
            "auth_migration_completed",
            "success",
            actor_user_id=target_admin_id,
            subject_user_id=target_admin_id,
            metadata={
                "mapped_admin_count": len(non_target_admins),
                "content_owner_count": len(report.owner_counts),
            },
        )
        await self.session.commit()
        return target_admin_id

    async def integrity_audit(self, storage: FileStorage) -> LibraryIntegrityReport:
        stored_files = list((await self.session.scalars(select(StoredFileModel))).all())
        database_keys = {stored_file.storage_key for stored_file in stored_files}
        physical_keys = storage.list_storage_keys()
        missing_permanent = database_keys - physical_keys
        unexpected_permanent = physical_keys - database_keys
        permanent_checksum_mismatches = 0
        for stored_file in stored_files:
            if stored_file.storage_key not in missing_permanent:
                if storage.calculate_checksum(stored_file.storage_key) != stored_file.sha256:
                    permanent_checksum_mismatches += 1

        imports = list((await self.session.scalars(select(LibraryImportModel))).all())
        temporary_checksums: dict[str, str | None] = {}
        for import_row in imports:
            for key, checksum in (
                (import_row.temporary_storage_key, import_row.sha256),
                (import_row.normalized_temporary_storage_key, None),
                (import_row.cover_temporary_storage_key, None),
                (import_row.cover_thumbnail_temporary_storage_key, None),
            ):
                if key is not None:
                    temporary_checksums[key] = checksum
        missing_temporary = 0
        temporary_checksum_mismatches = 0
        for key, checksum in temporary_checksums.items():
            if not storage.temporary_exists(key):
                missing_temporary += 1
            elif checksum is not None and storage.calculate_temporary_checksum(key) != checksum:
                temporary_checksum_mismatches += 1

        return LibraryIntegrityReport(
            database_permanent_files=len(database_keys),
            physical_permanent_files=len(physical_keys),
            referenced_temporary_files=len(temporary_checksums),
            missing_permanent_files=len(missing_permanent),
            unexpected_permanent_files=len(unexpected_permanent),
            permanent_checksum_mismatches=permanent_checksum_mismatches,
            missing_temporary_files=missing_temporary,
            temporary_checksum_mismatches=temporary_checksum_mismatches,
        )

    async def _total(self, model: Any) -> int:
        count = await self.session.scalar(select(func.count()).select_from(model))
        return int(count or 0)

    async def _count(self, model: Any, owner_column: Any, owner_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count()).select_from(model).where(owner_column == owner_id)
        )
        return int(count or 0)
