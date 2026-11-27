from datetime import date, datetime, timezone

import pytest

from src.domain.models.access import Scope
from src.domain.ports.report_query import ReportQuery
from src.infrastructure.repository.postgres_report_query import PostgresReportQuery

JAN, MAR = date(2024, 1, 1), date(2024, 3, 31)
ALL = Scope(subsidiary_id=None)


@pytest.fixture
def world(clean_pg):
    """Site A: ann (hired before January), bob (hired Jan 10, terminated Feb 10).
    Site B: dee (hired Feb 5). cy was hired in 2023 at A and transferred to B on Feb 15.
    Absences: ann Jan 15 and 16, bob Feb 1, dee Feb 20. ann was on time on Jan 17.
    One incident on Jan 20 at A with ann and bob, and one outside the range."""
    ids = {}
    with clean_pg.connection() as conn:
        for key, name in (("a", "Site A"), ("b", "Site B")):
            ids[key] = conn.execute(
                "INSERT INTO Subsidiary (name) VALUES (%s) RETURNING uniqueId", (name,)
            ).fetchone()[0]
        role = conn.execute("SELECT id FROM Role WHERE name = 'Employee'").fetchone()[0]
        for key, site, hired in (
            ("ann", "a", "2023-12-01"), ("bob", "a", "2024-01-10"),
            ("cy", "a", "2023-06-01"), ("dee", "b", "2024-02-05"),
        ):
            ids[key] = conn.execute(
                "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash, "
                "hired_at) VALUES (%s, %s, %s, %s, 'h', %s) RETURNING id",
                (ids[site], role, key.capitalize(), f"{key}@x.com", hired),
            ).fetchone()[0]
        conn.execute(
            "UPDATE Employee SET terminated_at = '2024-02-10', termination_reason = 'left' "
            "WHERE id = %s", (ids["bob"],),
        )
        conn.execute("UPDATE Employee SET subsidiary_id = %s WHERE id = %s", (ids["b"], ids["cy"]))
        conn.execute(
            "UPDATE EmployeeChange SET effective_date = '2024-02-15' "
            "WHERE change_type = 'TRANSFERRED'"
        )
        for who, day, status in (
            ("ann", "2024-01-15", "ABSENT"), ("ann", "2024-01-16", "ABSENT"),
            ("ann", "2024-01-17", "ON_TIME"), ("bob", "2024-02-01", "ABSENT"),
            ("dee", "2024-02-20", "ABSENT"), ("ann", "2024-04-01", "ABSENT"),
        ):
            meta = _meta(conn, ids[who])
            conn.execute(
                "INSERT INTO AssistanceRecord (employee_id, record_meta_id, status, "
                "occurred_at, work_date, reason) VALUES (%s, %s, %s, %s, %s, 'because, ok')",
                (ids[who], meta, status, f"{day} 12:00+00", day),
            )
        type_id = conn.execute("SELECT id FROM IncidentType WHERE name = 'Safety'").fetchone()[0]
        for day, people in (("2024-01-20", ("ann", "bob")), ("2024-06-01", ("ann",))):
            incident = conn.execute(
                "INSERT INTO Incident (record_meta_id, type, subsidiary_id, occurred_at, "
                "description) VALUES (%s, %s, %s, %s, 'fall') RETURNING id",
                (_meta(conn, ids["ann"]), type_id, ids["a"], f"{day} 12:00+00"),
            ).fetchone()[0]
            for who in people:
                conn.execute(
                    "INSERT INTO EmployeeIncident (incidentId, employeeId) VALUES (%s, %s)",
                    (incident, ids[who]),
                )
    return ids


def _meta(conn, author):
    return conn.execute(
        "INSERT INTO RecordMetadata (created_by, lastly_updated_by) VALUES (%s, %s) "
        "RETURNING id", (author, author),
    ).fetchone()[0]


def test_implements_port(pg_pool):
    assert isinstance(PostgresReportQuery(pg_pool), ReportQuery)


def test_turnover_counts_per_site_and_month(pg_pool, world):
    rows = PostgresReportQuery(pg_pool).turnover(ALL, date(2024, 1, 20), MAR)
    got = {
        (r.subsidiary_id, r.month.month): (
            r.hires, r.departures, r.absent_days, r.headcount_start, r.headcount_end
        )
        for r in rows
    }
    a, b = world["a"], world["b"]
    assert [(r.subsidiary_id, r.month) for r in rows] == [
        (s, date(2024, m, 1)) for s in sorted((a, b)) for m in (1, 2, 3)
    ]
    # Headcount follows the current site, so cy (transferred) counts at B for all months.
    assert got == {
        (a, 1): (1, 0, 2, 1, 2), (a, 2): (0, 1, 1, 2, 1), (a, 3): (0, 0, 0, 1, 1),
        (b, 1): (0, 0, 0, 1, 1), (b, 2): (1, 0, 1, 1, 2), (b, 3): (0, 0, 0, 2, 2),
    }
    assert rows[0].subsidiary_name in ("Site A", "Site B")


def test_turnover_scope_and_single_month(pg_pool, world):
    rows = PostgresReportQuery(pg_pool).turnover(
        Scope(subsidiary_id=world["b"]), date(2024, 2, 10), date(2024, 2, 20)
    )
    assert len(rows) == 1 and rows[0].subsidiary_id == world["b"]
    assert (rows[0].month, rows[0].hires, rows[0].absent_days) == (date(2024, 2, 1), 1, 1)
    assert PostgresReportQuery(pg_pool).turnover(Scope(subsidiary_id=999999), JAN, MAR) == []


def test_turnover_transfer_is_not_hire_or_departure(pg_pool, world):
    rows = PostgresReportQuery(pg_pool).turnover(ALL, date(2024, 2, 1), date(2024, 2, 1))
    # February has dee's hire and bob's departure. cy's move from A to B counts as neither.
    assert (sum(r.hires for r in rows), sum(r.departures for r in rows)) == (1, 1)


def test_absences_and_attendance_rows(pg_pool, world):
    query = PostgresReportQuery(pg_pool)
    absences = list(query.absences(ALL, JAN, MAR))
    assert [(r.work_date, r.employee_name) for r in absences] == [
        (date(2024, 1, 15), "Ann"), (date(2024, 1, 16), "Ann"),
        (date(2024, 2, 1), "Bob"), (date(2024, 2, 20), "Dee"),
    ]
    assert absences[0].reason == "because, ok" and absences[0].subsidiary_name == "Site A"
    assert absences[0].room_id is None
    own = list(query.attendance(Scope(subsidiary_id=world["a"]), JAN, MAR))
    assert [(r.work_date.day, r.status) for r in own] == [
        (15, "ABSENT"), (16, "ABSENT"), (17, "ON_TIME"), (1, "ABSENT"),
    ]
    assert own[0].occurred_at == datetime(2024, 1, 15, 12, tzinfo=timezone.utc)


def test_incidents_one_row_per_employee_within_range(pg_pool, world):
    rows = list(PostgresReportQuery(pg_pool).incidents(ALL, JAN, MAR))
    assert [r.employee_name for r in rows] == ["Ann", "Bob"]
    assert {r.incident_type for r in rows} == {"Safety"}
    assert rows[0].incident_id == rows[1].incident_id
    assert rows[0].description == "fall" and rows[0].registered_by_name == "Ann"
    assert list(PostgresReportQuery(pg_pool).incidents(Scope(subsidiary_id=world["b"]), JAN, MAR)) == []


def test_personnel_changes_include_transfer_for_both_sites(pg_pool, world):
    query = PostgresReportQuery(pg_pool)
    everyone = [(r.change_type, r.employee_name) for r in query.personnel_changes(ALL, JAN, MAR)]
    assert everyone == [
        ("HIRED", "Bob"), ("HIRED", "Dee"), ("TERMINATED", "Bob"), ("TRANSFERRED", "Cy"),
    ]
    site_a = list(query.personnel_changes(Scope(subsidiary_id=world["a"]), JAN, MAR))
    assert [(r.change_type, r.employee_name) for r in site_a] == [
        ("HIRED", "Bob"), ("TERMINATED", "Bob"), ("TRANSFERRED", "Cy"),
    ]
    transfer = site_a[2]
    assert (transfer.from_subsidiary_name, transfer.to_subsidiary_name) == ("Site A", "Site B")
    assert transfer.effective_date == date(2024, 2, 15)
    site_b = list(query.personnel_changes(Scope(subsidiary_id=world["b"]), JAN, MAR))
    assert [(r.change_type, r.employee_name) for r in site_b] == [
        ("HIRED", "Dee"), ("TRANSFERRED", "Cy"),
    ]
    hired = next(r for r in site_a if r.change_type == "HIRED")
    assert hired.from_subsidiary_id is None and hired.to_subsidiary_name == "Site A"


def test_streams_more_rows_than_one_chunk_and_releases_connection(pg_pool, world):
    with pg_pool.connection() as conn:
        meta_ids = conn.execute(
            "INSERT INTO RecordMetadata (created_by, lastly_updated_by) "
            "SELECT %s, %s FROM generate_series(1, 2100) RETURNING id",
            (world["ann"], world["ann"]),
        ).fetchall()
        conn.execute(
            "INSERT INTO AssistanceRecord (employee_id, record_meta_id, status, "
            "occurred_at, work_date) "
            "SELECT %s, m, 'LATE', date '2000-01-01' + n::int + time '12:00', date '2000-01-01' + n::int "
            "FROM unnest(%s::int[]) WITH ORDINALITY AS u(m, n)",
            (world["ann"], [r[0] for r in meta_ids]),
        )
    query = PostgresReportQuery(pg_pool)
    rows = list(query.attendance(ALL, date(2000, 1, 1), date(2010, 1, 1)))
    assert len(rows) == 2100  # more than two chunks of 1000
    for _ in range(6):  # the pool has 4 connections: abandoned iterators must give theirs back
        iterator = query.attendance(ALL, date(2000, 1, 1), date(2010, 1, 1))
        next(iterator)
        iterator.close()
