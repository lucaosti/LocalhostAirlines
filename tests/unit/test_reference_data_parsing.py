"""Parser tests against small embedded fixtures — no network (spec §21)."""

from providers.reference_data.openflights import parse_airlines, parse_airports
from providers.reference_data.ourairports import parse_csv

OURAIRPORTS_FIXTURE = (
    '"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent",'
    '"iso_country","iso_region","municipality","scheduled_service","icao_code","iata_code",'
    '"gps_code","local_code","home_link","wikipedia_link","keywords"\n'
    '1,"LIML","large_airport","Milano Malpensa",45.6306,8.7281,768,"EU","IT","IT-25",'
    '"Milano/Varese","yes","LIML","MXP","LIML",,,,\n'
    '2,"00A","heliport","Total RF Heliport",40.070985,-74.933689,11,"NA","US","US-PA",'
    '"Bensalem","no",,,"K00A","00A",,,\n'  # no IATA/ICAO — must be dropped
)

OPENFLIGHTS_AIRPORTS_FIXTURE = (
    '1,"Milano Malpensa","Milano","Italy","MXP","LIML",45.6306,8.7281,768,1,"E",'
    '"Europe/Rome","airport","OurAirports"\n'
    '2,"No Timezone Airport","Nowhere","Nowhere",\\N,"ZZZZ",0,0,0,0,"U",\\N,'
    '"airport","OurAirports"\n'
)

OPENFLIGHTS_AIRLINES_FIXTURE = (
    '1,"Air France",\\N,"AF","AFR","AIRFRANS","France","Y"\n'
    '2,"Defunct Air",\\N,"DA","DEF","DEFUNCT","Nowhere","N"\n'
    '3,"No ICAO Airline",\\N,"NA","","NOICAO","Nowhere","Y"\n'  # dropped: no ICAO
    # Real rows from the live feed (id -1 and id 1): both carry the literal
    # string "N/A" as ICAO, which is not the documented \N null marker and
    # collided on the primary key the first time this ran against real
    # data. Regression coverage for that.
    '-1,"Unknown",\\N,"-","N/A",\\N,\\N,"Y"\n'
    '1,"Private flight",\\N,"-","N/A","","","Y"\n'
    # Real corrupted row from the live feed (id 13394, "Jayrow"): a broken
    # escape sequence lands in the ICAO field. csv.reader parses it
    # "successfully" as a literal string — it takes format validation, not
    # just a presence check, to reject it.
    '13394,"Jayrow","",\\N,"\\\'\\\\","","Australia","Y"\n'
)


def test_ourairports_keeps_only_rows_with_both_codes() -> None:
    rows = parse_csv(OURAIRPORTS_FIXTURE)
    assert len(rows) == 1
    assert rows[0].icao_code == "LIML"
    assert rows[0].iata_code == "MXP"
    assert rows[0].municipality == "Milano/Varese"


def test_openflights_airports_parses_timezone_and_handles_null_marker() -> None:
    rows = parse_airports(OPENFLIGHTS_AIRPORTS_FIXTURE)
    by_icao = {r.icao_code: r for r in rows}
    assert by_icao["LIML"].timezone == "Europe/Rome"
    # ZZZZ has \N for IATA, so it must be dropped entirely (no usable code).
    assert "ZZZZ" not in by_icao


def test_openflights_airlines_parses_active_flag_and_drops_codeless_rows() -> None:
    rows = parse_airlines(OPENFLIGHTS_AIRLINES_FIXTURE)
    by_icao = {r.icao_code: r for r in rows}
    assert by_icao["AFR"].active is True
    assert by_icao["DEF"].active is False
    # Dropped: the ICAO-less row, both "N/A" placeholders, and the row with
    # a malformed ICAO field.
    assert len(rows) == 2
    assert "Jayrow" not in {r.name for r in rows}
