import pytest, sqlite3
from backend import services as S, transformations as T
from backend.database import conn
from tests.conftest import ready, executed
def test_all_transformations_work():
    assert T.apply("combine_fields",["John","Smith"],{"separator":" "})==["John Smith"]
    assert T.apply("split_field",["John Smith"],{},2)==["John","Smith"]
    assert T.apply("string_to_integer",["42"],{})==[42] and T.apply("integer_to_string",[7],{})==["7"]
    assert T.apply("null_to_default",[None],{"default":"x"})==["x"] and T.apply("string_uppercase",["a"],{})==["A"]
    with pytest.raises(T.TxError): T.apply("string_to_integer",["abc"],{})
    with pytest.raises(T.TxError): T.apply("eval",["1"],{})
def test_agent_has_no_execution_tools():
    from backend.agent import AgentTools
    assert not [n for n in dir(AgentTools) if any(w in n for w in("execute","insert","rollback"))]
def test_analysis_flags_risks_and_questions():
    pid=S.load_demo()["project_id"]; r=S.analyze(pid)
    assert any(x["severity"]=="HIGH" for x in r["plan"]["risks"]) and len(r["analysis"]["clarification_questions"])==4
def test_sample_limit_and_unsupported_mapping():
    pid=S.load_demo()["project_id"]
    with pytest.raises(S.ApiError) as e: S.set_samples(pid,[{"customer_id":str(i)} for i in range(51)])
    assert e.value.status==413
    pl=S.analyze(pid)["plan"]
    with pytest.raises(S.ApiError): S.add_mapping(pl["id"],{"sources":["email"],"targets":["phoneNumber"],"transform":"python_exec"})
def test_add_mapping_validation():
    pid=S.load_demo()["project_id"]; pl=S.analyze(pid)["plan"]
    with pytest.raises(S.ApiError): S.add_mapping(pl["id"],{"sources":["email"],"targets":["email"],"transform":"rename"})  # target already mapped
    with pytest.raises(S.ApiError): S.add_mapping(pl["id"],{"sources":["ghost"],"targets":["phoneNumber"],"transform":"rename"})
def test_approval_gates():
    pid=S.load_demo()["project_id"]; r=S.analyze(pid); pl=r["plan"]
    with pytest.raises(S.ApiError) as e: S.approve(pl["id"],"t",True)
    assert "high-severity" in e.value.msg
    for x in pl["risks"]: S.set_risk(pl["id"],x["id"],"RESOLVED")
    with pytest.raises(S.ApiError) as e: S.approve(pl["id"],"t",True)
    assert "clarification" in e.value.msg
def test_unapproved_cannot_dry_run_or_execute():
    _,p=ready(approve=False)
    with pytest.raises(S.ApiError): S.dry_run(p["id"])
    with pytest.raises(S.ApiError): S.execute(p["id"],1,True)
def test_dry_run_counts_evidence_and_determinism():
    _,p=ready(); d1=S.dry_run(p["id"]); d2=S.dry_run(p["id"])
    assert d1["summary"]["accepted"]==16 and d1["summary"]["rejected"]==4 and d1["summary"]["processed"]==20
    assert S.dry_records(d1["id"])==S.dry_records(d2["id"]) and d1["hash"]==d2["hash"]
    q={x["record_id"]:x for x in S.quarantine(p["project_id"],plan_version=1) if x["dry_run_id"]==d1["id"]}
    assert q["CUS-103"]["error_code"]=="INVALID_EMAIL" and q["CUS-104"]["error_code"]=="TRANSFORM_FAILED"
    assert q["CUS-104"]["actual_value"]=="32/14/2024" and q["CUS-106"]["error_message"].startswith("No enum mapping")
def test_execute_idempotent_and_audited():
    pid,p,d,r1=executed()
    assert r1["inserted"]==16
    r2=S.execute(p["id"],d["id"],True)
    assert r2["inserted"]==0 and r2["skipped"]==16 and len([t for t in S.target_rows() if t["mig"]])==16
    types=[e["event_type"] for e in S.history(pid)]
    assert {"PLAN_APPROVED","MIGRATION_STARTED","DUPLICATE_PREVENTED","MIGRATION_COMPLETED","RECORD_INSERTED"}<=set(types)
def test_db_unique_constraint():
    executed(); c=conn()
    with pytest.raises(sqlite3.IntegrityError): c.execute("INSERT INTO target(key,mig,run_id,rid,data) SELECT key,mig,run_id,rid,data FROM target WHERE mig IS NOT NULL LIMIT 1")
def test_plan_versioning_and_mismatch():
    pid,p,d,_=executed(); maps=p["maps"]; i=next(i for i,m in enumerate(maps) if m["targets"]==["customerId"]); maps[i]={**maps[i],"transform":"string_trim"}
    p2=S.update_mappings(p["id"],maps)
    assert p2["v"]==2 and not p2["approved"] and all(m["transform"]!="string_trim" for m in S.get_plan(p["id"])["maps"] if m["targets"]==["customerId"])
    assert S.compare(p["id"],p2["id"])["changed"]==["customerId"]
    for x in p2["risks"]:
        if x["status"]!="RESOLVED": S.set_risk(p2["id"],x["id"],"RESOLVED")
    S.approve(p2["id"],"t",True)
    with pytest.raises(S.ApiError) as e: S.execute(p2["id"],d["id"],True)
    assert "belongs to plan v1" in e.value.msg
    with pytest.raises(sqlite3.DatabaseError): conn().execute("UPDATE plans SET maps='[]' WHERE id=?",(p["id"],))
def test_reconcile_pass_missing_unexpected_duplicate():
    _,_,_,r=executed(); assert S.reconcile(r["id"])["status"]=="PASS"
    c=conn(); c.execute("DELETE FROM target WHERE rid='CUS-001'"); c.commit(); x=S.reconcile(r["id"])
    assert x["status"]=="FAIL" and x["missing_ids"]==["CUS-001"]
    c.execute("INSERT INTO target VALUES('X1',?,?, 'STRAY','{}')",(r["mig"],r["id"])); c.commit(); assert S.reconcile(r["id"])["unexpected_ids"]==["STRAY"]
    c.execute("INSERT INTO target VALUES('X2',?,?, 'CUS-002','{}')",(r["mig"],r["id"])); c.commit(); x=S.reconcile(r["id"]); assert x["duplicate_ids"]==["CUS-002"] and x["key_mismatches"]
def test_rollback_scoped_and_idempotent():
    pid,_,_,r=executed(); assert len(S.target_rows())==17
    out=S.rollback(r["id"],True); assert out["rolled_back"]==16 and out["untouched"]==1
    assert [t["key"] for t in S.target_rows()]==["SEED:EXT-001"]
    again=S.rollback(r["id"],True); assert again["rolled_back"]==0 and again["status"]=="NOOP" and len(S.target_rows())==1
    with pytest.raises(S.ApiError): S.rollback(r["id"],False)
    assert "ROLLBACK_COMPLETED" in [e["event_type"] for e in S.history(pid)]
    with pytest.raises(sqlite3.DatabaseError): conn().execute("UPDATE audit SET details='x'")
def test_persistence_across_connections():
    pid=S.load_demo()["project_id"]; assert S.proj(conn(),pid)["name"]=="Customer Migration Demo" and len(S.list_projects())==1
