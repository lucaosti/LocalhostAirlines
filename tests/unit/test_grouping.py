"""Pure clustering logic, no I/O (spec §5).

Real-world coordinates and airport_type throughout — the grouping algorithm's
whole history in this project is being disproven by exactly this kind of
real detail (see module docstring in grouping.py), so fixtures here use
actual OurAirports types, not simplified stand-ins.
"""

from domain.reference_data.grouping import GroupableAirport, derive_groups, haversine_km

# Real OurAirports data: all three are `large_airport`, confirmed against the
# live feed — the case that broke the first two designs.
MXP = GroupableAirport("LIMC", "MXP", "large_airport", "Milano/Varese", 45.6306, 8.7281)
LIN = GroupableAirport("LIML", "LIN", "large_airport", "Milano", 45.4451, 9.2767)
BGY = GroupableAirport("LIME", "BGY", "large_airport", "Bergamo", 45.6694, 9.7042)

# ~130km from Milan — a real large_airport that must NOT be pulled in.
TRN = GroupableAirport("LIMF", "TRN", "large_airport", "Torino", 45.2008, 7.6497)

FCO = GroupableAirport("LIRF", "FCO", "large_airport", "Roma", 41.8003, 12.2389)
CIA = GroupableAirport("LIRA", "CIA", "small_airport", "Roma", 41.7994, 12.5949)

# A synthetic medium_airport ~40km from MXP (near Como) — a regional feeder
# stand-in, since Milan's own real neighbours are all `large_airport`.
FEEDER = GroupableAirport("LIMZ", "CIY", "medium_airport", "Como", 45.8100, 9.0900)


def test_three_real_hubs_cluster_together_despite_different_municipalities() -> None:
    groups = derive_groups([MXP, LIN, BGY])
    assert len(groups) == 1
    assert groups[0].member_icao_codes == {"LIMC", "LIML", "LIME"}


def test_a_hub_130km_away_does_not_join_the_cluster() -> None:
    # The failure mode both earlier designs had: TRN is a real large_airport
    # within the naive single 100km radius of Milan's cluster members, but
    # 130km is not the same metro system.
    groups = derive_groups([MXP, LIN, BGY, TRN])
    milan = next(g for g in groups if "LIMC" in g.member_icao_codes)
    assert "LIMF" not in milan.member_icao_codes


def test_distant_single_hubs_do_not_form_a_group() -> None:
    groups = derive_groups([MXP, FCO])
    assert len(groups) == 0  # each is alone, no group of one


def test_small_airport_type_is_excluded_from_grouping() -> None:
    groups = derive_groups([FCO, CIA])
    assert len(groups) == 0  # CIA is small_airport, never a candidate


def test_medium_airport_attaches_to_nearest_hub() -> None:
    groups = derive_groups([MXP, LIN, BGY, FEEDER], member_radius_km=100.0)
    milan = next(g for g in groups if "LIMC" in g.member_icao_codes)
    assert "LIMZ" in milan.member_icao_codes


def test_group_anchor_is_deterministic_among_merged_hubs() -> None:
    groups = derive_groups([MXP, LIN, BGY])
    # Alphabetically first ICAO among the merged hubs (LIMC < LIME < LIML) —
    # arbitrary but stable; OurAirports carries no traffic-volume field to
    # rank by actual importance.
    assert groups[0].anchor_icao_code == "LIMC"
    assert groups[0].name == "Milano/Varese"


def test_haversine_known_distance() -> None:
    # MXP to LIN is a well-known ~45km hop.
    distance = haversine_km(45.6306, 8.7281, 45.4451, 9.2767)
    assert 40 < distance < 50
