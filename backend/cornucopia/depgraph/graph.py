"""Operational dependency graph.

Edges point from a resource to what consumes it:

    donation -> lot -> ingredient -> recipe -> batch -> meal -> commitment
                                     (substitute ingredient -.-> recipe)
    volunteer -> team -> batch            delivery -> commitment

``batch:<recipe>`` stands for the cooking of that recipe. Every team can cook
every recipe in this MVP, so each active team feeds every batch.

Impact of a change = the changed nodes plus everything downstream. For a
changed commitment (demand side) the upstream resources it draws on are
included as well, since their allocation changes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

import networkx as nx
from pydantic import BaseModel, ConfigDict

from cornucopia.compiler.snapshot import OperationalSnapshot


def nid(kind: str, id_: UUID | str) -> str:
    return f"{kind}:{id_}"


def build_graph(snap: OperationalSnapshot) -> nx.DiGraph:
    g = nx.DiGraph()

    def node(kind: str, id_: UUID, label: str, **attrs: Any) -> str:
        n = nid(kind, id_)
        g.add_node(n, kind=kind, id=str(id_), label=label, **attrs)
        return n

    for d in snap.donations:
        node("donation", d.id, d.description, status=d.status)
    for i in snap.ingredients:
        node("ingredient", i.id, i.name, base_unit=i.base_unit.value)
    for lot in snap.lots:
        ing = snap.ingredient.get(lot.ingredient_id)
        n = node(
            "lot",
            lot.id,
            f"{ing.name if ing else '?'} lot",
            status=lot.status,
            quantity_base=str(lot.quantity_base),
        )
        if lot.donation_id:
            g.add_edge(nid("donation", lot.donation_id), n, rel="supplies")
        g.add_edge(n, nid("ingredient", lot.ingredient_id), rel="stocks")
    for r in snap.recipes:
        rn = node("recipe", r.id, r.name)
        bn = node("batch", r.id, f"Cook {r.name}")
        g.add_edge(rn, bn, rel="cooked_as")
    for line in snap.recipe_ingredients:
        g.add_edge(
            nid("ingredient", line.ingredient_id),
            nid("recipe", line.recipe_id),
            rel="optional_in" if line.optional else "required_by",
        )
    for s in snap.substitutions:
        recipes = (
            [s.recipe_id]
            if s.recipe_id
            else [
                ln.recipe_id
                for ln in snap.recipe_ingredients
                if ln.ingredient_id == s.ingredient_id
            ]
        )
        for r_id in recipes:
            if not g.has_edge(nid("ingredient", s.substitute_id), nid("recipe", r_id)):
                g.add_edge(
                    nid("ingredient", s.substitute_id),
                    nid("recipe", r_id),
                    rel="substitute_for",
                    substitution_id=str(s.id),
                )
    for m in snap.meals:
        node("meal", m.id, m.name)
    for comp in snap.meal_components:
        g.add_edge(nid("batch", comp.recipe_id), nid("meal", comp.meal_id), rel="component_of")
    for t in snap.teams:
        tn = node("team", t.id, t.name, active=t.active)
        if t.active:
            for r in snap.recipes:
                g.add_edge(tn, nid("batch", r.id), rel="prepares")
    for v in snap.volunteers:
        vn = node("volunteer", v.id, v.name, role=v.role, available=v.available)
        if v.team_id:
            g.add_edge(vn, nid("team", v.team_id), rel="staffs")
    for dv in snap.deliveries:
        node("delivery", dv.id, dv.route_name, status=dv.status)
    for c in snap.commitments:
        cn = node("commitment", c.id, c.recipient, status=c.status, meals=c.meals_count)
        g.add_edge(nid("meal", c.meal_id), cn, rel="fulfils")
        if c.delivery_id:
            g.add_edge(nid("delivery", c.delivery_id), cn, rel="delivers")
    return g


class ImpactNode(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    kind: str
    label: str
    role: str  # origin | downstream | upstream


class ImpactEdge(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: str
    target: str
    rel: str


class Impact(BaseModel):
    model_config = ConfigDict(frozen=True)
    origins: tuple[str, ...]
    nodes: tuple[ImpactNode, ...]
    edges: tuple[ImpactEdge, ...]
    affected_commitments: tuple[str, ...]
    counts: dict[str, int]


def impact(g: nx.DiGraph, origins: Iterable[str]) -> Impact:
    seeds = sorted({o for o in origins if o in g})
    roles: dict[str, str] = {s: "origin" for s in seeds}
    for s in seeds:
        for d in nx.descendants(g, s):
            roles.setdefault(d, "downstream")
        if g.nodes[s]["kind"] == "commitment":
            for a in nx.ancestors(g, s):
                roles.setdefault(a, "upstream")
    sub = g.subgraph(roles)
    nodes = tuple(
        ImpactNode(id=n, kind=g.nodes[n]["kind"], label=g.nodes[n]["label"], role=roles[n])
        for n in sorted(roles)
    )
    edges = tuple(
        ImpactEdge(source=u, target=v, rel=d.get("rel", ""))
        for u, v, d in sorted(sub.edges(data=True), key=lambda e: (e[0], e[1]))
    )
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n.kind] = counts.get(n.kind, 0) + 1
    return Impact(
        origins=tuple(seeds),
        nodes=nodes,
        edges=edges,
        affected_commitments=tuple(n.id for n in nodes if n.kind == "commitment"),
        counts=dict(sorted(counts.items())),
    )


def event_origins(event_type: str, payload: dict[str, Any], effect: dict[str, Any]) -> list[str]:
    """Map a journaled operational event to the graph nodes it changed."""
    match event_type:
        case "DONATION_CREATED" | "DONATION_CANCELLED":
            return [nid("donation", effect.get("donation_id") or payload["donation_id"])]
        case "INVENTORY_ADJUSTED" | "INGREDIENT_EXPIRED":
            return [nid("lot", payload["lot_id"])]
        case "VOLUNTEER_UNAVAILABLE":
            return [nid("volunteer", payload["volunteer_id"])]
        case "DELIVERY_DELAYED" | "DELIVERY_CANCELLED":
            return [nid("delivery", payload["delivery_id"])]
        case "COMMITMENT_CHANGED":
            return [nid("commitment", payload["commitment_id"])]
        case "PREPARATION_CAPACITY_CHANGED":
            return [nid("team", payload["team_id"])]
    raise ValueError(f"unknown event type {event_type}")
