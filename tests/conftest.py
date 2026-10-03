import pytest
from backend import services as S
@pytest.fixture(autouse=True)
def db(tmp_path,monkeypatch): monkeypatch.setenv("DATABASE_URL",f"sqlite:///{tmp_path}/t.db")
def ready(approve=True):
    pid=S.load_demo()["project_id"]; r=S.analyze(pid); pl=r["plan"]
    for x in pl["risks"]: S.set_risk(pl["id"],x["id"],"RESOLVED")
    for q in r["analysis"]["clarification_questions"]: S.set_question(pid,q["id"],"RESOLVED","ok")
    return pid,(S.approve(pl["id"],"tester",True) if approve else pl)
def executed():
    pid,p=ready(); d=S.dry_run(p["id"]); return pid,p,d,S.execute(p["id"],d["id"],True)
