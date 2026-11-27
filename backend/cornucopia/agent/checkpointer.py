"""LangGraph checkpoint saver backed by Supabase through the Sprites connector.

The connector exposes PostgREST only, so LangGraph's Postgres checkpointer
(which needs a direct SQL connection) cannot be used. This saver stores each
checkpoint as one serialised blob (the graph's own serde, base64 encoded) via
idempotent RPCs, and reads them back with plain REST selects.

* ``put`` is idempotent: checkpoints are immutable, a replayed put is a no-op.
* ``put_writes`` follows LangGraph's rule: regular writes (idx >= 0) are never
  overwritten, special writes (errors, interrupts, idx < 0) may be replaced.
* Reads are scoped to the organization; every row carries organization_id.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator, Sequence
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

from cornucopia.persistence.client import SupabaseClient


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


class SupabaseCheckpointSaver(BaseCheckpointSaver[int]):
    def __init__(self, db: SupabaseClient, organization_id: UUID) -> None:
        super().__init__()
        self.db = db
        self.org = str(organization_id)

    # ---------------------------------------------------------------- reads
    def _rows(
        self, thread_id: str, ns: str, checkpoint_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        filters = {
            "organization_id": f"eq.{self.org}",
            "thread_id": f"eq.{thread_id}",
            "checkpoint_ns": f"eq.{ns}",
        }
        if checkpoint_id:
            filters["checkpoint_id"] = f"eq.{checkpoint_id}"
        return self.db.select(
            "agent_checkpoints", filters=filters, order="checkpoint_id.desc", limit=limit
        )

    def _writes(self, thread_id: str, ns: str, checkpoint_id: str) -> list[tuple[str, str, Any]]:
        rows = self.db.select(
            "agent_checkpoint_writes",
            filters={
                "organization_id": f"eq.{self.org}",
                "thread_id": f"eq.{thread_id}",
                "checkpoint_ns": f"eq.{ns}",
                "checkpoint_id": f"eq.{checkpoint_id}",
            },
        )
        rows.sort(key=lambda r: (r.get("task_path") or "", r["task_id"], int(r["idx"])))
        return [
            (
                r["task_id"],
                r["channel"],
                self.serde.loads_typed((r["value_type"], _unb64(r["value"]))),
            )
            for r in rows
        ]

    def _tuple(self, row: dict[str, Any]) -> CheckpointTuple:
        thread_id, ns, cid = row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"]
        checkpoint: Checkpoint = self.serde.loads_typed(
            (row["checkpoint_type"], _unb64(row["checkpoint"]))
        )
        metadata: CheckpointMetadata = self.serde.loads_typed(
            (row["metadata_type"], _unb64(row["metadata"]))
        )
        parent = row.get("parent_checkpoint_id")
        return CheckpointTuple(
            config={
                "configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": cid}
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": ns,
                        "checkpoint_id": parent,
                    }
                }
                if parent
                else None
            ),
            pending_writes=self._writes(thread_id, ns, cid),
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        conf = config["configurable"]
        rows = self._rows(
            conf["thread_id"], conf.get("checkpoint_ns", ""), get_checkpoint_id(config), limit=1
        )
        return self._tuple(rows[0]) if rows else None

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        if config is None:
            raise ValueError("SupabaseCheckpointSaver.list requires a thread_id")
        conf = config["configurable"]
        rows = self._rows(conf["thread_id"], conf.get("checkpoint_ns", ""))
        before_id = get_checkpoint_id(before) if before else None
        n = 0
        for row in rows:
            if before_id and row["checkpoint_id"] >= before_id:
                continue
            tup = self._tuple(row)
            if filter and any(tup.metadata.get(k) != v for k, v in filter.items()):
                continue
            yield tup
            n += 1
            if limit is not None and n >= limit:
                return

    # --------------------------------------------------------------- writes
    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        conf = config["configurable"]
        thread_id, ns = conf["thread_id"], conf.get("checkpoint_ns", "")
        ctype, cblob = self.serde.dumps_typed(checkpoint)
        full_meta = get_checkpoint_metadata(config, metadata)
        mtype, mblob = self.serde.dumps_typed(full_meta)
        values = checkpoint.get("channel_values", {})
        summary = {
            "step": full_meta.get("step"),
            "source": full_meta.get("source"),
            "node": values.get("current_node"),
            "channels": sorted(values.keys()),
        }
        self.db.rpc(
            "put_checkpoint",
            {
                "p_row": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": checkpoint["id"],
                    "organization_id": self.org,
                    "parent_checkpoint_id": conf.get("checkpoint_id"),
                    "checkpoint_type": ctype,
                    "checkpoint": _b64(cblob),
                    "metadata_type": mtype,
                    "metadata": _b64(mblob),
                    "summary": summary,
                }
            },
        )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        if not writes:
            return
        conf = config["configurable"]
        rows = []
        for idx, (channel, value) in enumerate(writes):
            vtype, vblob = self.serde.dumps_typed(value)
            rows.append(
                {
                    "thread_id": conf["thread_id"],
                    "checkpoint_ns": conf.get("checkpoint_ns", ""),
                    "checkpoint_id": conf["checkpoint_id"],
                    "task_id": task_id,
                    "idx": WRITES_IDX_MAP.get(channel, idx),
                    "organization_id": self.org,
                    "channel": channel,
                    "value_type": vtype,
                    "value": _b64(vblob),
                    "task_path": task_path,
                }
            )
        self.db.rpc("put_checkpoint_writes", {"p_rows": rows})

    def delete_thread(self, thread_id: str) -> None:
        raise NotImplementedError("checkpoints are an append-only audit trail")
