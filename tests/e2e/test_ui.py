"""Browser E2E: drives the real UI against a real uvicorn + SQLite. Run: python -m pytest tests/e2e"""
import json, os, sqlite3, subprocess, sys, time, urllib.request, pytest
from playwright.sync_api import sync_playwright, expect
PORT=8791; URL=f"http://127.0.0.1:{PORT}"
@pytest.fixture(scope="module")
def server(tmp_path_factory):
    db=f"{tmp_path_factory.mktemp('db')}/e2e.db"; env={**os.environ,"DATABASE_URL":f"sqlite:///{db}"}
    p=subprocess.Popen([sys.executable,"-m","uvicorn","backend.main:app","--port",str(PORT)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(50):
        try: urllib.request.urlopen(URL+"/api/projects"); break
        except Exception: time.sleep(0.2)
    yield db; p.terminate()
def nav(page,name): page.locator("nav").get_by_role("button",name=name,exact=True).click()
def q(db,sql):
    c=sqlite3.connect(db); r=c.execute(sql).fetchall(); c.close(); return r
def test_full_lifecycle_in_browser(server):
    with sync_playwright() as pw:
        b=pw.chromium.launch(); page=b.new_page(); errors=[]; page.on("pageerror",lambda e:errors.append(str(e))); page.goto(URL)
        page.get_by_role("button",name="Load Demo Migration").click(); expect(page.get_by_text("Customer Migration Demo").first).to_be_visible()
        page.reload(); expect(page.get_by_text("Customer Migration Demo").first).to_be_visible()        # persistence after refresh
        page.get_by_role("button",name="Open").click(); nav(page,"AI Analysis"); page.get_by_role("button",name="Run AI analysis").click()
        expect(page.get_by_text("Mapping proposals")).to_be_visible(); page.reload(); nav(page,"AI Analysis"); expect(page.get_by_text("Mapping proposals")).to_be_visible()
        nav(page,"Migration Plan"); expect(page.get_by_text("Draft").first).to_be_visible()
        row=page.locator("tr",has_text="phoneNumber").filter(has=page.get_by_role("button",name="Reject")); row.get_by_role("button",name="Reject").click(); expect(page.get_by_text("REJECTED",exact=True)).to_be_visible()
        page.get_by_role("button",name="+ Add Mapping").click(); page.locator("#ds").select_option("phone"); page.locator("#dg").select_option("phoneNumber"); page.locator("#dt").select_option("string_trim"); page.get_by_role("button",name="Save mapping").click()
        expect(page.locator("tr",has_text="string_trim").filter(has_text="phoneNumber")).to_be_visible()
        while (n:=page.get_by_role("button",name="Resolve",exact=True).count()):
            page.get_by_role("button",name="Resolve",exact=True).first.click(); expect(page.get_by_role("button",name="Resolve",exact=True)).to_have_count(n-1)
        while (n:=page.locator("select:has(option:text-is('RESOLVED'))").filter(has=page.locator("option:checked:text-is('OPEN')")).count()):
            page.locator("select:has(option:text-is('RESOLVED'))").filter(has=page.locator("option:checked:text-is('OPEN')")).first.select_option("RESOLVED"); page.wait_for_timeout(300)
        nav(page,"Approval"); page.get_by_label("I reviewed the mapping").check(); page.get_by_role("button",name="Approve Migration Plan").click(); expect(page.get_by_text("Approved",exact=True).first).to_be_visible()
        nav(page,"Dry Run"); page.get_by_role("button",name="Run dry run on v1").click()
        for label,val in[("Source records","20"),("Processed","20"),("Accepted","16"),("Rejected","4")]: expect(page.locator(".stat",has_text=label).first).to_contain_text(val)
        page.locator("tr.click",has_text="CUS-103").click(); expect(page.get_by_text("INVALID_EMAIL").first).to_be_visible()
        nav(page,"Quarantine"); expect(page.get_by_text("4 quarantine entries")).to_be_visible()
        nav(page,"Execute"); page.get_by_label("I understand this will execute").check(); page.get_by_role("button",name="Approve & Execute Migration").click(); expect(page.locator(".stat",has_text="Inserted").first).to_contain_text("16")
        page.get_by_label("I understand this will execute").check(); page.get_by_role("button",name="Retry Migration").click(); expect(page.get_by_text("0 duplicate records created").first).to_be_visible()
        assert q(server,"SELECT COUNT(*),COUNT(DISTINCT key),COUNT(DISTINCT rid) FROM target WHERE mig IS NOT NULL")==[(16,16,16)]   # DB-level: 0 duplicates
        assert q(server,"SELECT inserted,skipped FROM runs ORDER BY id")==[(16,0),(0,16)]
        assert q(server,"SELECT COUNT(*) FROM target WHERE mig IS NULL")==[(1,)]
        nav(page,"Reconciliation"); page.get_by_role("button",name="Reconcile run #2").click(); expect(page.get_by_text("PASS").first).to_be_visible()
        nav(page,"Rollback"); page.get_by_label("I confirm rolling back run #1").check(); page.get_by_role("button",name="Confirm Rollback").first.click()
        expect(page.get_by_text("Rolled back: 16 · Failed: 0 · Untouched: 1")).to_be_visible()
        assert q(server,"SELECT key FROM target")==[("SEED:EXT-001",)]                                 # unrelated row survived, migration rows gone
        assert q(server,"SELECT records_rolled_back,status FROM rollbacks")==[(16,"COMPLETED")]       # rollback count == insert count
        nav(page,"Execute"); expect(page.get_by_text("SEED:EXT-001")).to_be_visible()
        page.reload(); nav(page,"Dry Run"); expect(page.locator(".stat",has_text="Accepted").first).to_contain_text("16"); expect(page.locator(".stat",has_text="Rejected").first).to_contain_text("4")   # dry run persisted
        nav(page,"Reconciliation"); expect(page.get_by_text("PASS").first).to_be_visible()                # reconciliation persisted
        nav(page,"Quarantine"); expect(page.get_by_text("4 quarantine entries")).to_be_visible()
        page.reload(); nav(page,"History"); expect(page.get_by_text("ROLLBACK_COMPLETED")).to_be_visible(); expect(page.get_by_text("DUPLICATE_PREVENTED")).to_be_visible()
        ev={r[0] for r in q(server,"SELECT type FROM audit")}
        assert {"PROJECT_CREATED","SCHEMA_ADDED","SAMPLE_DATA_ADDED","AI_ANALYSIS_COMPLETED","MAPPING_CREATED","RISK_RESOLVED","QUESTION_ANSWERED","PLAN_APPROVED","DRY_RUN_COMPLETED","RECORD_QUARANTINED","MIGRATION_STARTED","RECORD_INSERTED","DUPLICATE_PREVENTED","MIGRATION_COMPLETED","RECONCILIATION_COMPLETED","ROLLBACK_COMPLETED"}<=ev, ev
        assert not errors, errors; b.close()

def test_every_transformation_selectable_and_configurable(server):
    reg=[t["name"] for t in json.load(urllib.request.urlopen(URL+"/api/transformations"))]
    assert len(reg)==12
    with sync_playwright() as pw:
        b=pw.chromium.launch(); page=b.new_page(); page.goto(URL)
        page.get_by_role("button",name="Open").last.click(); nav(page,"Migration Plan"); page.get_by_role("button",name="+ Add Mapping").click()
        assert page.locator("#dt option").all_text_contents()==reg                                       # list comes from backend registry
        fields={"date_format":"#p_input_format","null_to_default":"#p_default","enum_mapping":"#p_mapping","combine_fields":"#p_separator","split_field":"#p_separator"}
        for t in reg:
            page.locator("#dt").select_option(t)
            if t in fields: expect(page.locator(fields[t])).to_be_visible()
            else: expect(page.locator("#dp")).to_contain_text("No parameters")
        page.locator("#dt").select_option("combine_fields"); page.locator("#ds").select_option(["first_name","last_name"]); page.locator("#dg").select_option("lastName")  # backend rejects: type/field rules
        page.get_by_role("button",name="Save mapping").click(); expect(page.locator("#de")).not_to_be_empty()
        b.close()
