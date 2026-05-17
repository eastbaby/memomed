import unittest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.models import MmCareSubjectAlias
from app.subjects.schemas import SubjectResponse
from app.subjects.service import _archive_aliases_for_subject, normalize_alias


class SubjectRegistryServiceTests(unittest.TestCase):
    def test_normalize_alias_collapses_spaces_and_casefolds(self) -> None:
        self.assertEqual(normalize_alias(" 我的  Cat "), "我的 cat")

    def test_normalize_alias_normalizes_full_width_chars(self) -> None:
        self.assertEqual(normalize_alias("ＡＢＣ"), "abc")


class FakeSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement


class SubjectRegistryAliasArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_archive_aliases_for_subject_only_targets_active_aliases(self) -> None:
        session = FakeSession()
        subject_id = uuid4()

        await _archive_aliases_for_subject(session, subject_id, "default")

        compiled = str(session.statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("UPDATE mm_care_subject_aliases", compiled)
        self.assertIn("status='active'", compiled.replace(" ", ""))
        self.assertIn("status='archived'", compiled.replace(" ", ""))
        self.assertEqual(session.statement.table.name, MmCareSubjectAlias.__tablename__)


class SubjectRegistryRouteTests(unittest.TestCase):
    def test_get_subjects_uses_subject_registry_route(self) -> None:
        now = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
        subject = SubjectResponse(
            id="subject-1",
            owner_user_id="default",
            subject_type="pet",
            display_name="小橘",
            legal_name=None,
            relation_type="pet",
            species="cat",
            breed=None,
            gender=None,
            birth_date=None,
            status="active",
            notes=None,
            created_at=now,
            updated_at=now,
            aliases=[],
        )

        with patch("app.subjects.routes.list_subjects", new=AsyncMock(return_value=[subject])):
            response = TestClient(app).get("/api/subjects")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["display_name"], "小橘")
        self.assertEqual(payload[0]["subject_type"], "pet")


if __name__ == "__main__":
    unittest.main()
