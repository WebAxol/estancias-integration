"""Each mapped constraint is provoked on the real schema and translated.

Every case runs inside one transaction that is rolled back, so no data remains.
"""
import psycopg
import pytest
from psycopg import errors as pg

from src.application.errors import (
    AttendanceAlreadyRecordedError,
    CapacitationAlreadyAssignedError,
    ClientUuidConflictError,
    ConflictError,
    EmailAlreadyRegisteredError,
    IntegrityRuleError,
    RoomNameTakenError,
)
from src.infrastructure.repository.pg_errors import translate

CLIENT_UUID = "11111111-1111-1111-1111-111111111111"


def _one(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def _employee(conn, sub, email, room=None):
    return _one(
        conn,
        "INSERT INTO Employee (subsidiary_id, room_id, roleId, name, email, password_hash) "
        "VALUES (%s, %s, (SELECT min(id) FROM Role WHERE id > 0), 'N', %s, 'x') RETURNING id",
        (sub, room, email),
    )


def _meta(conn, emp):
    return _one(
        conn,
        "INSERT INTO RecordMetadata (created_by, lastly_updated_by) VALUES (%s, %s) RETURNING id",
        (emp, emp),
    )


def _base(conn):
    sub = _one(conn, "INSERT INTO Subsidiary (name) VALUES ('S1') RETURNING uniqueId")
    room = _one(
        conn, "INSERT INTO Room (subsidiary_id, name) VALUES (%s, 'R1') RETURNING uniqueId", (sub,)
    )
    emp = _employee(conn, sub, "ana@x.com")
    return {"sub": sub, "room": room, "emp": emp}


def _assist(conn, emp, status, client_uuid=None):
    conn.execute(
        "INSERT INTO AssistanceRecord (employee_id, record_meta_id, status, client_uuid) "
        "VALUES (%s, %s, %s, %s)",
        (emp, _meta(conn, emp), status, client_uuid),
    )


def _incident(conn, emp, client_uuid=None):
    type_id = _one(conn, "SELECT min(id) FROM IncidentType")
    return _one(
        conn,
        "INSERT INTO Incident (record_meta_id, type, client_uuid) VALUES (%s, %s, %s) RETURNING id",
        (_meta(conn, emp), type_id, client_uuid),
    )


def _assign(conn, emp, cap):
    conn.execute(
        "INSERT INTO EmployeeCapacitation (employeeId, capacitationId, record_meta_id) "
        "VALUES (%s, %s, %s)",
        (emp, cap, _meta(conn, emp)),
    )


def _capacitation(conn, emp):
    return _one(
        conn,
        "INSERT INTO Capacitation (record_meta_id, name) VALUES (%s, 'C') RETURNING id",
        (_meta(conn, emp),),
    )


def _duplicate_email(conn, b):
    _employee(conn, b["sub"], "ANA@x.com")


def _day_twice(conn, b):
    _assist(conn, b["emp"], "ON_TIME")
    _assist(conn, b["emp"], "LATE")


def _exit_twice(conn, b):
    _assist(conn, b["emp"], "EXITED")
    _assist(conn, b["emp"], "EXITED")


def _assist_uuid_twice(conn, b):
    _assist(conn, b["emp"], "ON_TIME", CLIENT_UUID)
    _assist(conn, b["emp"], "EXITED", CLIENT_UUID)


def _incident_uuid_twice(conn, b):
    _incident(conn, b["emp"], CLIENT_UUID)
    _incident(conn, b["emp"], CLIENT_UUID)


def _pending_twice(conn, b):
    cap = _capacitation(conn, b["emp"])
    _assign(conn, b["emp"], cap)
    _assign(conn, b["emp"], cap)


def _room_name_twice(conn, b):
    conn.execute("INSERT INTO Room (subsidiary_id, name) VALUES (%s, 'R1')", (b["sub"],))


def _repeated_in_incident(conn, b):
    incident = _incident(conn, b["emp"])
    for _ in range(2):
        conn.execute(
            "INSERT INTO EmployeeIncident (incidentId, employeeId) VALUES (%s, %s)",
            (incident, b["emp"]),
        )


def _subsidiary_name_twice(conn, b):
    conn.execute("INSERT INTO Subsidiary (name) VALUES ('S1')")


def _negative_required(conn, b):
    conn.execute("UPDATE Room SET required_personal = -1 WHERE uniqueId = %s", (b["room"],))


def _termination_before_hire(conn, b):
    conn.execute(
        "UPDATE Employee SET terminated_at = hired_at - 1 WHERE id = %s", (b["emp"],)
    )


def _capacitation_dates(conn, b):
    conn.execute(
        "INSERT INTO Capacitation (record_meta_id, name, starts_at, due_at) "
        "VALUES (%s, 'C', '2025-02-01', '2025-01-01')",
        (_meta(conn, b["emp"]),),
    )


def _capacitation_state(conn, b):
    cap = _capacitation(conn, b["emp"])
    conn.execute(
        "INSERT INTO EmployeeCapacitation (employeeId, capacitationId, record_meta_id, is_pending) "
        "VALUES (%s, %s, %s, FALSE)",
        (b["emp"], cap, _meta(conn, b["emp"])),
    )


def _schedule_times(conn, b):
    schedule = _one(
        conn,
        "INSERT INTO Schedule (name, record_meta_id) VALUES ('H', %s) RETURNING id",
        (_meta(conn, b["emp"]),),
    )
    conn.execute(
        "INSERT INTO ScheduleDay (scheduleId, day, entry_time, exit_time) "
        "VALUES (%s, (SELECT min(e) FROM unnest(enum_range(NULL::day_of_week)) e), '10:00', '09:00')",
        (schedule,),
    )


def _arco_resolution(conn, b):
    conn.execute(
        "INSERT INTO ArcoRequest (employee_id, request_type, status) "
        "VALUES (%s, 'ACCESS', 'RESOLVED')",
        (b["emp"],),
    )


def _missing_role(conn, b):
    conn.execute(
        "INSERT INTO Employee (subsidiary_id, roleId, name, email, password_hash) "
        "VALUES (%s, 9999, 'N', 'z@x.com', 'x')",
        (b["sub"],),
    )


def _room_of_other_site(conn, b):
    other = _one(conn, "INSERT INTO Subsidiary (name) VALUES ('S2') RETURNING uniqueId")
    _employee(conn, other, "bob@x.com", room=b["room"])


def _alias_on_null_site(conn, b):
    conn.execute(
        "INSERT INTO RoleAlias (subsidiary_id, role_id, alias, record_meta_id) "
        "VALUES (0, (SELECT min(id) FROM Role WHERE id > 0), 'A', %s)",
        (_meta(conn, b["emp"]),),
    )


UNIQUE_CASES = [
    ("ux_employee_email_lower", _duplicate_email, EmailAlreadyRegisteredError),
    ("ux_assistance_employee_day", _day_twice, AttendanceAlreadyRecordedError),
    ("ux_assistance_employee_day_exit", _exit_twice, AttendanceAlreadyRecordedError),
    ("ux_assistance_client_uuid", _assist_uuid_twice, ClientUuidConflictError),
    ("ux_incident_client_uuid", _incident_uuid_twice, ClientUuidConflictError),
    ("ux_employee_capacitation_pending", _pending_twice, CapacitationAlreadyAssignedError),
    ("uq_room_name_per_subsidiary", _room_name_twice, RoomNameTakenError),
    ("uq_subsidiary_name", _subsidiary_name_twice, ConflictError),
]

RULE_CASES = [
    ("uq_employee_incident", _repeated_in_incident),
    ("ck_room_required_personal", _negative_required),
    ("ck_employee_termination", _termination_before_hire),
    ("ck_capacitation_dates", _capacitation_dates),
    ("ck_employee_capacitation_state", _capacitation_state),
    ("ck_schedule_day_times", _schedule_times),
    ("ck_arco_resolution", _arco_resolution),
    ("foreign key", _missing_role),
    ("trg_employee_room", _room_of_other_site),
    ("trg_role_alias_check", _alias_on_null_site),
]


def _provoke(pool, action):
    """Run `action` on a fresh base and return the integrity error it raises."""
    with pool.connection() as conn:
        try:
            base = _base(conn)
            with pytest.raises(psycopg.errors.IntegrityError) as caught:
                action(conn, base)
            return caught.value
        finally:
            conn.rollback()


@pytest.mark.parametrize("constraint,action,expected", UNIQUE_CASES, ids=[c[0] for c in UNIQUE_CASES])
def test_unique_violation_maps_to_application_error(pg_pool, constraint, action, expected):
    exc = _provoke(pg_pool, action)
    assert isinstance(exc, pg.UniqueViolation)
    assert exc.diag.constraint_name == constraint or constraint == "ux_employee_email_lower"
    assert type(translate(exc)) is expected


@pytest.mark.parametrize("constraint,action", RULE_CASES, ids=[c[0] for c in RULE_CASES])
def test_rule_violation_maps_to_fixed_message(pg_pool, constraint, action):
    exc = _provoke(pg_pool, action)
    error = translate(exc)
    assert type(error) is IntegrityRuleError
    message = str(error)
    assert message
    assert str(exc.diag.message_primary) not in message
    assert "INSERT" not in message and "UPDATE" not in message


def test_each_check_constraint_has_its_own_message(pg_pool):
    cases = [action for name, action in RULE_CASES if name.startswith("ck_")]
    messages = {str(translate(_provoke(pg_pool, action))) for action in cases}
    assert len(messages) == len(cases)
