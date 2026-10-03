"""Backend must enforce rules independently of the UI."""
import pytest, sqlite3
from fastapi.testclient import TestClient
from backend import services as S, transformations as T
from backend.database import conn
from backend.main import app
from tests.conftest import ready, executed
c=TestClient(app)
def test_draft_plan_cannot_execute_or_dry_run():
    _,p=ready(approve=False)
    assert c.post(f"/api/plans/{p['id']}/execute",json={"dry_run_id":1,"confirm":True}).status_code==409
    assert "not been approved" in c.post(f"/api/plans/{p['id']}/dry-run").json()["detail"]
def test_no_matching_dry_run_and_stale_samples():
    pid,p=ready(); assert c.post(f"/api/plans/{p['id']}/execute",json={"dry_run_id":999,"confirm":True}).status_code==404
    d=S.dry_run(p["id"]); S.set_samples(pid,S.proj(conn(),pid)["recs"][:10])
    with pytest.raises(S.ApiError) as e: S.execute(p["id"],d["id"],True)
    assert "sample data has changed" in e.value.msg
def test_confirmation_required():
    _,p=ready(); d=S.dry_run(p["id"]); assert c.post(f"/api/plans/{p['id']}/execute",json={"dry_run_id":d["id"],"confirm":False}).status_code==422
def test_sample_limit_and_invalid_inputs_over_http():
    pid=c.post("/api/demo").json()["project_id"]
    assert c.post(f"/api/projects/{pid}/sample-records",json={"records":[{"customer_id":str(i)} for i in range(51)]}).status_code==413
    assert c.post(f"/api/projects/{pid}/sample-records",json={"records":[{"nope":1}]}).status_code==422
    assert c.post(f"/api/projects/{pid}/source-schema",json={"a":{"type":"weird"}}).status_code==422
    pl=c.post(f"/api/projects/{pid}/analyze").json()["plan"]["id"]
    bad={"sources":["email"],"targets":["phoneNumber"],"transform":"__import__('os')","params":{}}
    assert c.post(f"/api/plans/{pl}/mappings",json=bad).status_code==422
    assert c.post(f"/api/plans/{pl}/mappings",json={**bad,"transform":"date_format","params":{"input_format":"%Y;rm"}}).status_code==422
def test_idempotency_at_database_level():
    _,p,d,r1=executed(); S.execute(p["id"],d["id"],True); db=conn()
    assert db.execute("SELECT COUNT(*),COUNT(DISTINCT key),COUNT(DISTINCT rid) FROM target WHERE mig IS NOT NULL").fetchone()[:]==(16,16,16)
    assert [r["inserted"] for r in S.list_runs(p["project_id"])]==[16,0] and S.list_runs(p["project_id"])[1]["skipped"]==16
def test_rollback_isolation_and_noop_audit():
    pid,p,d,r=executed(); db=conn(); S.rollback(r["id"],True); before=db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    assert [x["key"] for x in db.execute("SELECT key FROM target")]==["SEED:EXT-001"]
    assert S.rollback(r["id"],True)["status"]=="NOOP"
    ev=[e["event_type"] for e in S.history(pid)]
    assert ev.count("ROLLBACK_COMPLETED")==1 and ev.count("ROLLBACK_STARTED")==1 and ev.count("ROLLBACK_NOOP")==1
    assert db.execute("SELECT COUNT(*) FROM rollbacks").fetchone()[0]==1 and len(S.target_rows())==1
CASES={"rename":(["a"],{},1,["a"]),"string_trim":([" a "],{},1,["a"]),"string_lowercase":(["AB"],{},1,["ab"]),"string_uppercase":(["ab"],{},1,["AB"]),
 "date_format":(["14/03/1992"],{},1,["1992-03-14"]),"integer_to_string":([7],{},1,["7"]),"string_to_integer":(["42"],{},1,[42]),"boolean_normalization":(["Yes"],{},1,[True]),
 "null_to_default":([None],{"default":"n/a"},1,["n/a"]),"enum_mapping":(["m"],{"mapping":{"M":"MALE"}},1,["MALE"]),"combine_fields":(["John","Smith"],{"separator":" "},1,["John Smith"]),"split_field":(["John Smith"],{"separator":" "},2,["John","Smith"])}
BAD={"date_format":(["32/14/2024"],{}),"string_to_integer":(["abc"],{}),"boolean_normalization":(["maybe"],{}),"enum_mapping":(["Q"],{"mapping":{"M":"MALE"}})}
@pytest.mark.parametrize("name",sorted(CASES))
def test_each_transformation_valid_and_registered(name):
    v,p,n,exp=CASES[name]; assert T.apply(name,v,p,n)==exp and any(t["name"]==name for t in c.get("/api/transformations").json())
@pytest.mark.parametrize("name",sorted(BAD))
def test_each_transformation_invalid(name):
    with pytest.raises(T.TxError): T.apply(name,*[BAD[name][0],BAD[name][1]])
def test_status_endpoint():
    s=c.get("/api/status").json(); assert s["database"]=="SQLite" and s["ai_mode"]=="Mock" and s["source"]==1 and s["sample_limit"]==50
