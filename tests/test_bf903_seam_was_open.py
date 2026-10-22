"""BF-903 (#1581): the seam was open. Written against names that exist before BF-903, so on that tree this test
fails for its premise (a visiting officer without ward_room.post opens a thread), not on an import. After BF-903
the Ward Room has no registry attached here, so the visitor is refused with ``visitor_registry_off``."""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.identity import AgentIdentityRegistry
from probos.visiting_officers import VisitingOfficerRegistry
from probos.ward_room.service import WardRoomService


async def test_a_visitor_without_ward_room_post_cannot_open_a_thread(tmp_path: Path) -> None:
    identities = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    ward_room = WardRoomService(db_path=str(tmp_path / "wr.db"), identity_registry=identities)
    try:
        await identities.start()
        await identities.start(instance_id="bf903-open-ship", vessel_name="Bf903open", version="1")
        await ward_room.start()
        officers = VisitingOfficerRegistry(
            identities, instance_id="bf903-open-ship", vessel_name="Bf903open", baseline_version="1",
        )
        reader = await officers.register("reader", ["ward_room.read"])
        channel = await ward_room.get_channel_by_name("All Hands")
        before = await ward_room.count_threads(channel.id)
        with pytest.raises(PermissionError):
            await ward_room.create_thread(channel.id, reader.did, "Not allowed", "body")
        assert await ward_room.count_threads(channel.id) == before
    finally:
        await ward_room.stop()
        await identities.stop()
