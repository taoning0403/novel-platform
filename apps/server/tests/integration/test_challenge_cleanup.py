import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from novel_platform.application.auth.webauthn_service import WebAuthnService
from novel_platform.application.errors import ApplicationError
from novel_platform.domain.auth.models import WebAuthnChallengePurpose
from novel_platform.infrastructure.database.models import (
    UserModel,
    WebAuthnChallengeModel,
)
from novel_platform.infrastructure.repositories.credentials import CredentialRepository


@pytest.mark.integration
async def test_expired_challenge_cleanup_is_bounded_and_preserves_valid(app_harness) -> None:
    admin = await app_harness.provision_admin()
    admin_id = admin.user_id
    now = datetime.now(UTC)

    def challenge_row(*, expired: bool) -> WebAuthnChallengeModel:
        return WebAuthnChallengeModel(
            challenge=secrets.token_bytes(32),
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            user_id=admin_id,
            expected_origin="http://localhost:3000",
            rp_id=app_harness.settings.webauthn_rp_id,
            expires_at=now - timedelta(minutes=1) if expired else now + timedelta(minutes=5),
            created_at=now,
        )

    async with app_harness.session_factory() as session:
        session.add_all([challenge_row(expired=True) for _ in range(12)])
        session.add_all([challenge_row(expired=False) for _ in range(2)])
        await session.commit()

    async with app_harness.session_factory() as session:
        repository = CredentialRepository(session)
        assert await repository.delete_expired_challenges(batch_size=5) == 5
        await session.commit()
        assert await repository.delete_expired_challenges(batch_size=5) == 5
        await session.commit()
        assert await repository.delete_expired_challenges(batch_size=5) == 2
        await session.commit()
        assert await repository.delete_expired_challenges(batch_size=5) == 0
        remaining = await session.scalar(select(func.count(WebAuthnChallengeModel.id)))
        assert remaining == 2

    # Issuing new challenges triggers the bounded cleanup and keeps valid rows.
    async with app_harness.session_factory() as session:
        session.add_all([challenge_row(expired=True) for _ in range(3)])
        await session.commit()
    async with app_harness.session_factory() as session:
        service = WebAuthnService(session, app_harness.settings)
        options = await service.authentication_options(origin="http://localhost:3000")
        assert options.challenge_id
        remaining = await session.scalar(select(func.count(WebAuthnChallengeModel.id)))
        assert remaining == 3  # two valid fixtures plus the newly issued challenge


@pytest.mark.integration
async def test_challenge_verification_remains_single_use_under_concurrency(app_harness) -> None:
    admin = await app_harness.provision_admin()
    admin_id = admin.user_id
    now = datetime.now(UTC)
    challenge_id = uuid4()
    async with app_harness.session_factory() as session:
        session.add(
            WebAuthnChallengeModel(
                id=challenge_id,
                challenge=secrets.token_bytes(32),
                purpose=WebAuthnChallengePurpose.AUTHENTICATION,
                user_id=admin_id,
                expected_origin="http://localhost:3000",
                rp_id=app_harness.settings.webauthn_rp_id,
                expires_at=now + timedelta(minutes=5),
                created_at=now,
            )
        )
        await session.commit()

    lock_held = asyncio.Event()

    async def consume() -> None:
        async with app_harness.session_factory() as session:
            service = WebAuthnService(session, app_harness.settings)
            user = await session.get(UserModel, admin_id)
            assert user is not None
            challenge = await service._challenge(
                challenge_id,
                WebAuthnChallengePurpose.AUTHENTICATION,
                user,
                "http://localhost:3000",
            )
            lock_held.set()
            await asyncio.sleep(0.3)
            challenge.used_at = datetime.now(UTC)
            await session.commit()

    async def replay() -> None:
        await lock_held.wait()
        async with app_harness.session_factory() as session:
            service = WebAuthnService(session, app_harness.settings)
            user = await session.get(UserModel, admin_id)
            assert user is not None
            with pytest.raises(ApplicationError) as error:
                await service._challenge(
                    challenge_id,
                    WebAuthnChallengePurpose.AUTHENTICATION,
                    user,
                    "http://localhost:3000",
                )
            assert error.value.code == "invalid_webauthn_challenge"

    await asyncio.gather(consume(), replay())
