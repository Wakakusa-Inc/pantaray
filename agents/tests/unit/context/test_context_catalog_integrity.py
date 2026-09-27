from contextlib import closing

import pytest
from tests.unit.local_runtime.test_memory_catalog import _connection

from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_memory_document,
)
from pantaray_agents.local_runtime.memory_catalog.errors import (
    MemoryCatalogIntegrityError,
)
from pantaray_agents.local_runtime.memory_catalog.models import MemoryDocument
from pantaray_agents.local_runtime.memory_catalog.revision_inspection import (
    inspect_revision,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction


@pytest.mark.parametrize("source_path", ["body.md", "repo/example.py#L1-L3"])
def test_inline_inspection_uses_published_path_and_still_rejects_corruption(
    tmp_path, source_path
):
    with closing(_connection(tmp_path)) as connection:
        document = MemoryDocument(source_path, "Observed file contents")
        with immediate_transaction(connection):
            revision = register_inline_memory_document(
                connection=connection,
                user_id="user-1",
                source="action_file_read",
                source_record_id="known-read",
                document=document,
            )
        arguments = {
            "connection": connection,
            "artifact_root": tmp_path / "artifacts",
            "user_id": "user-1",
            "revision_id": revision.revision_id,
        }
        inspected = inspect_revision(**arguments)
        assert inspected.documents == (document,)
        assert not inspected.needs_link_repair
        connection.execute(
            "UPDATE memory_revisions SET inline_body = inline_body || ' changed' "
            "WHERE revision_id = ?",
            (revision.revision_id,),
        )
        with pytest.raises(MemoryCatalogIntegrityError, match="hash changed"):
            inspect_revision(**arguments)
