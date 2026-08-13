"""Airport group derivation: pure distance-based clustering, no I/O (spec §5).

Groups exist for the multi-origin / nearby-airport feature (spec §27, §34) —
e.g. Milan should surface MXP, LIN and BGY together. OurAirports' own
`municipality` field cannot do this alone: Malpensa's municipality is
"Milano/Varese", Linate's is "Milano", Bergamo's is "Bergamo" — string
matching would put them in different groups despite serving the same metro
area. Distance is therefore the actual clustering signal; municipality only
supplies the group's display name, taken from the anchor.

Two designs were tried and discarded before this one, each only disproven by
running against the real, full-density OurAirports + OpenFlights dataset —
small fixtures could not have caught either failure:

1. Single-linkage clustering over every groupable airport. Transitive
   chaining through Western Europe's dense airport network produced a
   267-airport "Milan" group spanning Belgium to Switzerland.
2. Nearest-single-anchor assignment, no anchor-to-anchor merging. This
   under-grouped: MXP, LIN and BGY are all `large_airport` in the real data
   (Malpensa, Linate *and* Bergamo are each major hubs), so refusing to ever
   merge two anchors left Milan's three airports in three separate groups —
   directly contradicting the motivating example.

The design here uses two different radii for two different questions:
hub_radius_km asks "are these two major airports the same metro system",
member_radius_km asks "is this regional airport served by that metro
system". Verified against the real dataset: hub_radius_km=50 is tight enough
that Milan's cluster is exactly {MXP, LIN, BGY} — Turin and Verona, both
`large_airport` and within the naive 100km radius, are correctly excluded.
"""

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0

# Only commercially-relevant, IATA-coded airports participate in grouping.
# General aviation strips and heliports are stored as reference data but
# would produce meaningless clusters here.
GROUPABLE_TYPES = frozenset({"large_airport", "medium_airport"})
ANCHOR_TYPE = "large_airport"

DEFAULT_HUB_RADIUS_KM = 50.0
DEFAULT_MEMBER_RADIUS_KM = 100.0


@dataclass(frozen=True)
class GroupableAirport:
    icao_code: str
    iata_code: str
    airport_type: str
    municipality: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class AirportGroup:
    name: str
    anchor_icao_code: str
    member_icao_codes: frozenset[str]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, (lat1, lon1, lat2, lon2))
    d_lat = lat2_r - lat1_r
    d_lon = lon2_r - lon1_r
    a = sin(d_lat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_a] = root_b


def derive_groups(
    airports: list[GroupableAirport],
    hub_radius_km: float = DEFAULT_HUB_RADIUS_KM,
    member_radius_km: float = DEFAULT_MEMBER_RADIUS_KM,
) -> list[AirportGroup]:
    """Two passes. First, hubs (large_airport) within hub_radius_km of each
    other merge via single-linkage — hubs are sparse enough relative to the
    full airport set that chaining stays local (verified against real data;
    see module docstring). Second, every medium_airport joins the single
    nearest hub within member_radius_km, measured directly to that hub only
    — never transitively through another member, which is what caused the
    267-airport failure this design replaced.
    """
    candidates = [a for a in airports if a.airport_type in GROUPABLE_TYPES]
    hubs = [a for a in candidates if a.airport_type == ANCHOR_TYPE]
    members = [a for a in candidates if a.airport_type != ANCHOR_TYPE]

    hub_uf = _UnionFind([h.icao_code for h in hubs])
    for i, a in enumerate(hubs):
        for b in hubs[i + 1 :]:
            if haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) <= hub_radius_km:
                hub_uf.union(a.icao_code, b.icao_code)

    clusters: dict[str, list[GroupableAirport]] = {}
    for hub in hubs:
        clusters.setdefault(hub_uf.find(hub.icao_code), []).append(hub)

    hub_by_code = {h.icao_code: h for h in hubs}

    for candidate in members:
        nearest_hub: GroupableAirport | None = None
        nearest_distance = member_radius_km
        for hub in hubs:
            distance = haversine_km(
                candidate.latitude, candidate.longitude, hub.latitude, hub.longitude
            )
            if distance <= nearest_distance:
                nearest_hub = hub
                nearest_distance = distance
        if nearest_hub is not None:
            clusters[hub_uf.find(nearest_hub.icao_code)].append(candidate)

    groups = []
    for cluster_members in clusters.values():
        if len(cluster_members) < 2:
            continue
        # The anchor is whichever hub in the cluster has the alphabetically
        # first ICAO code — a real, if arbitrary, tie-break: OurAirports
        # carries no traffic-volume field to rank hubs by actual importance.
        cluster_hubs = sorted(
            (m for m in cluster_members if m.icao_code in hub_by_code), key=lambda h: h.icao_code
        )
        anchor = cluster_hubs[0]
        groups.append(
            AirportGroup(
                name=anchor.municipality,
                anchor_icao_code=anchor.icao_code,
                member_icao_codes=frozenset(m.icao_code for m in cluster_members),
            )
        )
    return groups
