from fastapi.testclient import TestClient
from backend.main import app
c=TestClient(app)
def test_full_lifecycle_over_http():
    pid=c.post("/api/demo").json()["project_id"]; a=c.post(f"/api/projects/{pid}/analyze").json(); pl=a["plan"]["id"]
    assert c.post(f"/api/plans/{pl}/approve",json={"confirm":True}).status_code==409
    for r in a["plan"]["risks"]: c.post(f"/api/plans/{pl}/risks/{r['id']}",json={"status":"RESOLVED"})
    for q in a["analysis"]["clarification_questions"]: c.post(f"/api/projects/{pid}/questions/{q['id']}",json={"status":"ANSWERED"}) # answered is not resolved-open
    assert c.post(f"/api/plans/{pl}/approve",json={"confirm":True}).status_code==200
    assert c.post(f"/api/plans/{pl}/execute",json={"dry_run_id":1,"confirm":True}).status_code==404
    d=c.post(f"/api/plans/{pl}/dry-run").json(); assert (d["summary"]["accepted"],d["summary"]["rejected"])==(16,4)
    assert len(c.get(f"/api/projects/{pid}/quarantine?field=birthDate").json())==1
    r=c.post(f"/api/plans/{pl}/execute",json={"dry_run_id":d["id"],"confirm":True}).json(); rid=r["id"]
    assert c.post(f"/api/plans/{pl}/execute",json={"dry_run_id":d["id"],"confirm":True}).json()["skipped"]==16
    assert c.post(f"/api/migration-runs/{rid}/reconcile").json()["status"]=="PASS"
    assert c.post(f"/api/migration-runs/{rid}/rollback",json={"confirm":True}).json()["rolled_back"]==16
    assert c.post(f"/api/migration-runs/{rid}/rollback",json={"confirm":True}).json()["status"]=="NOOP"
    assert len(c.get(f"/api/projects/{pid}/history").json())>30
def test_list_endpoints_and_cors_free_static():
    pid=c.post("/api/demo").json()["project_id"]; p=c.get("/api/projects").json()[0]
    assert p["plan_version"] is None and c.get(f"/api/projects/{pid}/dry-runs").json()==[] and c.get(f"/api/projects/{pid}/migration-runs").json()==[]
    a=c.post(f"/api/projects/{pid}/analyze").json(); assert c.get(f"/api/plans/{a['plan']['id']}").json()["analysis"]["missing_fields"]==[]
