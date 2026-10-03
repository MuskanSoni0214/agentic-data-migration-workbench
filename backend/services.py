import hashlib, json, os, sqlite3
from .database import conn, dumps, now
from . import transformations as T
from .agent import AgentTools, get_agent
L=json.loads
class ApiError(Exception):
    def __init__(s,status,msg): s.status,s.msg=status,msg; super().__init__(msg)
def sha(o): return hashlib.sha256(dumps(o).encode()).hexdigest()[:16]
def must(r,what):
    if r is None: raise ApiError(404,f"{what} not found")
    return r
def log(c,t,pid,details,plan_v=None,run_id=None,actor="demo.user"):
    c.execute("INSERT INTO audit(ts,type,project_id,plan_v,run_id,actor,details) VALUES(?,?,?,?,?,?,?)",(now(),t,pid,plan_v,run_id,actor,details))
def proj(c,pid):
    r=must(c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone(),"Project")
    return {**dict(r),"src":L(r["src"] or "{}"),"tgt":L(r["tgt"] or "{}"),"recs":L(r["recs"] or "[]"),"qs":L(r["qs"])}
def plan_row(c,plan_id):
    r=must(c.execute("SELECT * FROM plans WHERE id=?",(plan_id,)).fetchone(),"Plan")
    return {"id":r["id"],"project_id":r["project_id"],"v":r["v"],"approved":bool(r["approved"]),"maps":L(r["maps"]),"risks":L(r["risks"]),"approval":L(r["approval"]) if r["approval"] else None,"note":r["note"],"analysis":L(r["analysis"]) if r["analysis"] else None}
def create_project(name,source_name,target_name,max_n=None):
    cap=int(os.environ.get("MAX_SAMPLE_SIZE","50")); max_n=max_n or cap
    if not name.strip(): raise ApiError(422,"Project name required")
    if not 1<=max_n<=500: raise ApiError(422,"max sample size must be 1..500")
    c=conn(); cur=c.execute("INSERT INTO projects(name,source_name,target_name,max_n) VALUES(?,?,?,?)",(name,source_name,target_name,max_n))
    log(c,"PROJECT_CREATED",cur.lastrowid,name); c.commit(); return proj(c,cur.lastrowid)
def list_projects():
    c=conn(); out=[]
    for r in c.execute("SELECT * FROM projects ORDER BY id"):
        pl=c.execute("SELECT v,approved FROM plans WHERE project_id=? ORDER BY v DESC",(r["id"],)).fetchone(); run=c.execute("SELECT id,rolled,ts FROM runs WHERE project_id=? ORDER BY id DESC",(r["id"],)).fetchone()
        rc=c.execute("SELECT result FROM recons WHERE run_id=? ORDER BY id DESC",(run["id"],)).fetchone() if run else None
        last=c.execute("SELECT MAX(ts) FROM audit WHERE project_id=?",(r["id"],)).fetchone()[0]
        out.append({"id":r["id"],"name":r["name"],"max_n":r["max_n"],"source_name":r["source_name"],"target_name":r["target_name"],"plan_version":pl["v"] if pl else None,"plan_approved":bool(pl["approved"]) if pl else None,"last_run":dict(run) if run else None,"reconciliation":L(rc[0])["status"] if rc else None,"updated_at":last})
    return out
def list_dry_runs(pid):
    c=conn(); proj(c,pid); return [{"id":r["id"],"plan_id":r["plan_id"],"plan_version":r["plan_v"],"created_at":r["ts"],"hash":r["hash"],"summary":L(r["result"])["summary"]} for r in c.execute("SELECT * FROM dry_runs WHERE project_id=? ORDER BY id",(pid,))]
def list_runs(pid):
    c=conn(); proj(c,pid); out=[]
    for r in c.execute("SELECT id FROM runs WHERE project_id=? ORDER BY id",(pid,)):
        rb=[dict(x) for x in c.execute("SELECT * FROM rollbacks WHERE run_id=? ORDER BY id",(r["id"],))]; out.append({**run_get(r["id"]),"rollbacks":rb})
    return out
def set_schema(pid,kind,schema):
    if not isinstance(schema,dict) or not schema: raise ApiError(422,"Schema must be a non-empty object")
    for k,v in schema.items():
        if not isinstance(v,dict) or v.get("type") not in("string","integer","boolean","date","enum"): raise ApiError(422,f"Invalid type for field {k}")
        if v["type"]=="enum" and not v.get("values"): raise ApiError(422,f"Enum field {k} needs values")
    c=conn(); proj(c,pid); c.execute(f"UPDATE projects SET {kind}=? WHERE id=?",(dumps(schema),pid))
    log(c,"SCHEMA_ADDED",pid,f"{'source' if kind=='src' else 'target'} schema with {len(schema)} fields"); c.commit(); return schema
def set_samples(pid,records):
    c=conn(); p=proj(c,pid)
    if not isinstance(records,list) or not all(isinstance(r,dict) for r in records): raise ApiError(422,"Records must be a list of objects")
    if len(records)>p["max_n"]: raise ApiError(413,f"{len(records)} records exceeds maximum sample size {p['max_n']}")
    if not p["src"]: raise ApiError(409,"Add the source schema first")
    for r in records:
        extra=set(r)-set(p["src"])
        if extra: raise ApiError(422,f"Record has fields not in source schema: {sorted(extra)}")
    c.execute("UPDATE projects SET recs=? WHERE id=?",(dumps(records),pid)); log(c,"SAMPLE_DATA_ADDED",pid,f"{len(records)} records"); c.commit(); return len(records)
def check_maps(maps,src,tgt):
    seen={}
    for i,m in enumerate(maps):
        if m.get("status")=="REJECTED": continue
        e=T.validate_mapping(m,src,tgt)
        if e: raise ApiError(422,f"Mapping {i} invalid: {'; '.join(e)}")
        for t in m["targets"]:
            if t in seen: raise ApiError(422,f"Target {t} is mapped more than once")
            seen[t]=i
def analyze(pid):
    c=conn(); p=proj(c,pid)
    if not (p["src"] and p["tgt"] and p["recs"]): raise ApiError(409,"Source schema, target schema and samples are required")
    log(c,"AI_ANALYSIS_STARTED",pid,"Planning agent invoked (read-only tools)")
    try: a=get_agent().analyze(AgentTools(p["src"],p["tgt"],p["recs"]))
    except NotImplementedError as x: raise ApiError(501,str(x))
    qs=[{"id":i+1,**q,"status":"OPEN","answer":None,"resolved_by":None,"resolved_at":None} for i,q in enumerate(a["clarification_questions"])]
    v=(c.execute("SELECT MAX(v) FROM plans WHERE project_id=?",(pid,)).fetchone()[0] or 0)+1
    cur=c.execute("INSERT INTO plans(project_id,v,maps,risks,note,analysis) VALUES(?,?,?,?,?,?)",(pid,v,dumps(a["mappings"]),dumps([{"id":i+1,**r} for i,r in enumerate(a["risks"])]),"AI-generated",dumps({k:a[k] for k in("missing_fields","incompatible_fields","suggested_transformations")})))
    c.execute("UPDATE projects SET qs=? WHERE id=?",(dumps(qs),pid))
    log(c,"AI_ANALYSIS_COMPLETED",pid,f"{len(a['mappings'])} mappings, {len(a['risks'])} risks, {len(qs)} questions",v); log(c,"PLAN_CREATED",pid,f"Plan v{v} (draft)",v); c.commit()
    return {"plan":plan_row(c,cur.lastrowid),"analysis":{**a,"clarification_questions":qs}}
def list_plans(pid): c=conn(); proj(c,pid); return [plan_row(c,r[0]) for r in c.execute("SELECT id FROM plans WHERE project_id=? ORDER BY v",(pid,))]
def get_plan(plan_id): return plan_row(conn(),plan_id)
def _new_version(c,p,note):
    v=c.execute("SELECT MAX(v) FROM plans WHERE project_id=?",(p["project_id"],)).fetchone()[0]+1
    cur=c.execute("INSERT INTO plans(project_id,v,maps,risks,note) VALUES(?,?,?,?,?)",(p["project_id"],v,dumps(p["maps"]),dumps(p["risks"]),note))
    log(c,"PLAN_CREATED",p["project_id"],f"Plan v{v} created from v{p['v']}; v{p['v']} unchanged",v); return plan_row(c,cur.lastrowid)
def update_mappings(plan_id,maps,created=False):
    c=conn(); p=plan_row(c,plan_id); pr=proj(c,p["project_id"]); check_maps(maps,pr["src"],pr["tgt"])
    if p["approved"]: p=_new_version(c,p,f"Edited from v{p['v']}")
    c.execute("UPDATE plans SET maps=? WHERE id=?",(dumps(maps),p["id"]))
    log(c,"MAPPING_CREATED" if created else "MAPPING_UPDATED",p["project_id"],f"{len(maps)} mappings on plan v{p['v']}",p["v"]); c.commit(); return plan_row(c,p["id"])
def add_mapping(plan_id,m):
    c=conn(); p=plan_row(c,plan_id)
    m={**m,"params":m.get("params") or {},"status":"ACCEPTED","confidence":"HIGH","reason":"Added manually","risk":"LOW"}
    if any(x["sources"]==m["sources"] and x["targets"]==m["targets"] and x["transform"]==m["transform"] for x in p["maps"]): raise ApiError(422,"Duplicate mapping definition")
    return update_mappings(plan_id,p["maps"]+[m],created=True)
def set_risk(plan_id,rid,status):
    c=conn(); p=plan_row(c,plan_id)
    if p["approved"]: raise ApiError(409,"Approved plan is immutable")
    r=next((x for x in p["risks"] if x["id"]==rid),None)
    if not r: raise ApiError(404,"Risk not found")
    r["status"]=status; c.execute("UPDATE plans SET risks=? WHERE id=?",(dumps(p["risks"]),plan_id))
    if status=="RESOLVED": log(c,"RISK_RESOLVED",p["project_id"],f"Risk {rid}: {r['field']}",p["v"])
    else: log(c,"RISK_REOPENED",p["project_id"],f"Risk {rid}: {r['field']}",p["v"])
    c.commit(); return r
def set_question(pid,qid,status,answer=None,by="demo.user"):
    c=conn(); p=proj(c,pid); q=next((x for x in p["qs"] if x["id"]==qid),None)
    if not q: raise ApiError(404,"Question not found")
    q["status"]=status
    if answer is not None: q["answer"]=answer
    if status=="RESOLVED": q["resolved_by"],q["resolved_at"]=by,now()
    c.execute("UPDATE projects SET qs=? WHERE id=?",(dumps(p["qs"]),pid)); log(c,"QUESTION_ANSWERED",pid,f"Q{qid} -> {status}"); c.commit(); return q
def approve(plan_id,approved_by,confirm):
    c=conn(); p=plan_row(c,plan_id); pr=proj(c,p["project_id"])
    if p["approved"]: raise ApiError(409,"Plan already approved")
    if not confirm: raise ApiError(422,"Explicit confirmation required")
    hi=[r for r in p["risks"] if r["severity"]=="HIGH" and r["status"]!="RESOLVED"]
    if hi: raise ApiError(409,f"Cannot approve: {len(hi)} high-severity risk(s) remain unresolved")
    op=[q for q in pr["qs"] if q["status"]=="OPEN"]
    if op: raise ApiError(409,f"Cannot approve: {len(op)} open clarification question(s)")
    mapped={t for m in p["maps"] if m.get("status")!="REJECTED" for t in m["targets"]}
    miss=[t for t,s in pr["tgt"].items() if s.get("required") and t not in mapped]
    if miss: raise ApiError(409,f"Required target fields unmapped: {miss}")
    ap={"approved_by":approved_by,"approved_at":now(),"plan_version":p["v"],"approval_action":"Approve Migration Plan"}
    c.execute("UPDATE plans SET approved=1,approval=? WHERE id=?",(dumps(ap),plan_id)); log(c,"PLAN_APPROVED",p["project_id"],f"Plan v{p['v']} approved by {approved_by}",p["v"],actor=approved_by); c.commit(); return plan_row(c,plan_id)
def compare(a,b):
    c=conn(); A,B=plan_row(c,a),plan_row(c,b); k=lambda p:{"|".join(m["targets"]):m for m in p["maps"]}; ka,kb=k(A),k(B)
    return {"from":A["v"],"to":B["v"],"added":sorted(set(kb)-set(ka)),"removed":sorted(set(ka)-set(kb)),"changed":sorted(x for x in set(ka)&set(kb) if dumps(ka[x])!=dumps(kb[x]))}
def run_record(rec,idx,maps,src,tgt,idf):
    rid=rec.get(idf) or f"ROW-{idx+1}"; ev=[]; out={}; ok=True
    for m in maps:
        if m.get("status")=="REJECTED": continue
        vals=[rec.get(s) for s in m["sources"]]; e={"sources":dict(zip(m["sources"],vals)),"transform":m["transform"],"outputs":{},"ok":True,"errors":[]}
        bad=[(s,v) for s,v in zip(m["sources"],vals) if v is not None and src[s]["type"]=="string" and not isinstance(v,str)]
        try:
            if bad: raise T.TxError(f"Source type error: {bad[0][0]} is not a string")
            res=T.apply(m["transform"],vals,m.get("params"),len(m["targets"]))
        except T.TxError as x:
            res=[None]*len(m["targets"]); e["errors"].append({"field":m["targets"][0],"code":"TRANSFORM_FAILED","message":str(x),"expected":tgt[m["targets"][0]]["type"],"actual":vals[0] if vals else None})
        for t,v in zip(m["targets"],res):
            e["outputs"][t]=v; out[t]=v
            if not e["errors"]:
                ce=T.check_target(tgt[t],v)
                if ce: e["errors"].append({"field":t,"code":ce[0],"message":ce[1],"expected":"|".join(tgt[t]["values"]) if tgt[t]["type"]=="enum" else tgt[t]["type"],"actual":v})
        e["ok"]=not e["errors"]; ok&=e["ok"]; ev.append(e)
    return {"rid":rid,"idx":idx,"source_hash":sha(rec),"source":rec,"ok":ok,"target":out,"evidence":ev}
def dry_run(plan_id):
    c=conn(); p=plan_row(c,plan_id); pr=proj(c,p["project_id"])
    if not p["approved"]: raise ApiError(409,"Cannot run dry run: migration plan has not been approved")
    idf=next((k for k in sorted(pr["src"]) if k.lower().endswith("id") or k.lower().endswith("_id")),next(iter(pr["src"]))); log(c,"DRY_RUN_STARTED",p["project_id"],f"Plan v{p['v']}",p["v"]); recs=[]; seen=set()
    for i,r in enumerate(pr["recs"]):
        x=run_record(r,i,p["maps"],pr["src"],pr["tgt"],idf)
        if r.get(idf) and r[idf] in seen: x["ok"]=False; x["evidence"].append({"sources":{idf:r[idf]},"transform":"-","outputs":{},"ok":False,"errors":[{"field":idf,"code":"DUPLICATE_ID","message":"Duplicate source ID","expected":"unique","actual":r[idf]}]})
        seen.add(r.get(idf)); recs.append(x)
    quar=[]
    for x in recs:
        for e in x["evidence"]:
            for er in e["errors"]: quar.append({"record_id":x["rid"],"source_record":x["source"],"failed_field":er["field"],"source_value":list(e["sources"].values())[0] if e["sources"] else None,"transformation":e["transform"],"expected_type":er["expected"],"expected_value":er["expected"],"actual_value":er["actual"],"error_code":er["code"],"error_message":er["message"],"plan_version":p["v"]})
    acc=sum(x["ok"] for x in recs); tx=sum(q["error_code"]=="TRANSFORM_FAILED" for q in quar)
    res={"records":recs,"quarantine":quar,"summary":{"source":len(recs),"processed":len(recs),"accepted":acc,"rejected":len(recs)-acc,"transformation_errors":tx,"validation_errors":len(quar)-tx}}
    cur=c.execute("INSERT INTO dry_runs(project_id,plan_id,plan_v,result,hash,ts) VALUES(?,?,?,?,?,?)",(p["project_id"],plan_id,p["v"],dumps(res),sha([pr["recs"],p["maps"]]),now()))
    log(c,"DRY_RUN_COMPLETED",p["project_id"],f"#{cur.lastrowid}: {acc} accepted, {len(recs)-acc} rejected",p["v"])
    if len(recs)>acc: log(c,"RECORD_QUARANTINED",p["project_id"],f"{len(recs)-acc} records",p["v"])
    c.commit(); return dry_get(cur.lastrowid)
def dry_get(did,full=False):
    r=must(conn().execute("SELECT * FROM dry_runs WHERE id=?",(did,)).fetchone(),"Dry run"); res=L(r["result"])
    out={"id":r["id"],"plan_id":r["plan_id"],"plan_version":r["plan_v"],"hash":r["hash"],"created_at":r["ts"],"summary":res["summary"]}
    if full: out["records"]=res["records"]
    return out
def dry_records(did,status=None):
    recs=L(must(conn().execute("SELECT result FROM dry_runs WHERE id=?",(did,)).fetchone(),"Dry run")["result"])["records"]
    return [x for x in recs if status is None or x["ok"]==(status=="accepted")]
def quarantine(pid,field=None,code=None,plan_version=None,record_id=None):
    c=conn(); proj(c,pid); out=[]
    for r in c.execute("SELECT id,result,plan_v,ts FROM dry_runs WHERE project_id=? ORDER BY id",(pid,)):
        for q in L(r["result"])["quarantine"]:
            if (field in(None,q["failed_field"])) and (code in(None,q["error_code"])) and (plan_version in(None,q["plan_version"])) and (record_id in(None,q["record_id"])): out.append({**q,"dry_run_id":r["id"],"timestamp":r["ts"]})
    return out
def execute(plan_id,dry_run_id,confirm):
    c=conn(); p=plan_row(c,plan_id); pr=proj(c,p["project_id"])
    if not confirm: raise ApiError(422,"Explicit confirmation required")
    if not p["approved"]: raise ApiError(409,"Cannot execute: migration plan has not been approved")
    d=must(c.execute("SELECT * FROM dry_runs WHERE id=?",(dry_run_id,)).fetchone(),"Dry run")
    if d["plan_id"]!=plan_id: raise ApiError(409,f"Cannot execute: dry run belongs to plan v{d['plan_v']} but execution is for plan v{p['v']}")
    if d["hash"]!=sha([pr["recs"],p["maps"]]): raise ApiError(409,"Migration rejected: sample data has changed since the dry run")
    mig=f"P{p['project_id']}-V{p['v']}"; retry=c.execute("SELECT COUNT(*) FROM runs WHERE mig=?",(mig,)).fetchone()[0]>0
    acc=[x for x in L(d["result"])["records"] if x["ok"]]
    cur=c.execute("INSERT INTO runs(project_id,plan_id,plan_v,dry_id,mig,processed,inserted,skipped,failed,ts) VALUES(?,?,?,?,?,?,0,0,0,?)",(p["project_id"],plan_id,p["v"],dry_run_id,mig,len(acc),now())); rid=cur.lastrowid
    log(c,"MIGRATION_STARTED",p["project_id"],f"Run #{rid} ({mig}){' retry' if retry else ''}",p["v"],rid); ins=sk=0
    for x in acc:
        try:
            c.execute("INSERT INTO target(key,mig,run_id,rid,data) VALUES(?,?,?,?,?)",(f"{mig}:{x['rid']}:customers",mig,rid,x["rid"],dumps(x["target"]))); ins+=1
            log(c,"RECORD_INSERTED",p["project_id"],x["rid"],p["v"],rid)
        except sqlite3.IntegrityError: sk+=1
    c.execute("UPDATE runs SET inserted=?,skipped=? WHERE id=?",(ins,sk,rid))
    if sk: log(c,"DUPLICATE_PREVENTED",p["project_id"],f"{sk} already present; 0 duplicates created",p["v"],rid)
    log(c,"MIGRATION_COMPLETED",p["project_id"],f"inserted {ins}, skipped {sk}, failed 0",p["v"],rid); c.commit(); return run_get(rid)
def run_get(rid):
    r=must(conn().execute("SELECT * FROM runs WHERE id=?",(rid,)).fetchone(),"Migration run"); return {**dict(r),"rolled":bool(r["rolled"]),"already_existed":r["skipped"]}
def target_rows(): return [{"key":r["key"],"mig":r["mig"],"run_id":r["run_id"],"rid":r["rid"],"data":L(r["data"])} for r in conn().execute("SELECT * FROM target ORDER BY key")]
def reconcile(rid):
    c=conn(); run=run_get(rid); d=L(c.execute("SELECT result FROM dry_runs WHERE id=?",(run["dry_id"],)).fetchone()[0])
    exp=[x["rid"] for x in d["records"] if x["ok"]]; rows=c.execute("SELECT key,rid FROM target WHERE mig=?",(run["mig"],)).fetchall(); act=[r["rid"] for r in rows]
    miss=sorted(set(exp)-set(act)); unexp=sorted(set(act)-set(exp)); dup=sorted({a for a in act if act.count(a)>1}); badk=sorted(r["key"] for r in rows if r["key"]!=f"{run['mig']}:{r['rid']}:customers")
    ok=not(miss or unexp or dup or badk) and len(exp)==len(act)
    res={"source_total":d["summary"]["source"],"accepted_total":len(exp),"quarantined_total":d["summary"]["rejected"],"expected_target_total":len(exp),"actual_target_total":len(act),"missing_ids":miss,"unexpected_ids":unexp,"duplicate_ids":dup,"key_mismatches":badk,"status":"PASS" if ok else "FAIL"}
    log(c,"RECONCILIATION_STARTED",run["project_id"],f"Run #{rid}",run["plan_v"],rid)
    c.execute("INSERT INTO recons(run_id,result,ts) VALUES(?,?,?)",(rid,dumps(res),now())); log(c,"RECONCILIATION_COMPLETED",run["project_id"],res["status"],run["plan_v"],rid); c.commit(); return res
def recon_get(rid):
    r=conn().execute("SELECT result FROM recons WHERE run_id=? ORDER BY id DESC",(rid,)).fetchone()
    if not r: raise ApiError(404,"No reconciliation yet")
    return L(r[0])
def rollback(rid,confirm,by="demo.user"):
    c=conn(); run=run_get(rid)
    if not confirm: raise ApiError(422,"Explicit confirmation required")
    if run["rolled"]:
        log(c,"ROLLBACK_NOOP",run["project_id"],f"Run #{rid} already rolled back; nothing changed",run["plan_v"],rid,by); c.commit()
        return {"migration_run_id":rid,"rolled_back":0,"untouched":c.execute("SELECT COUNT(*) FROM target").fetchone()[0],"failed":0,"status":"NOOP"}
    log(c,"ROLLBACK_STARTED",run["project_id"],f"Run #{rid}",run["plan_v"],rid,by)
    n=c.execute("DELETE FROM target WHERE run_id=?",(rid,)).rowcount; status="NOOP" if run["rolled"] else "COMPLETED"
    c.execute("UPDATE runs SET rolled=1 WHERE id=?",(rid,)); un=c.execute("SELECT COUNT(*) FROM target").fetchone()[0]
    c.execute("INSERT INTO rollbacks(run_id,performed_by,performed_at,records_rolled_back,status) VALUES(?,?,?,?,?)",(rid,by,now(),n,status))
    log(c,"ROLLBACK_COMPLETED",run["project_id"],f"{n} rolled back, {un} untouched ({status})",run["plan_v"],rid,by); c.commit()
    return {"migration_run_id":rid,"rolled_back":n,"untouched":un,"failed":0,"status":status}
def history(pid):
    c=conn(); proj(c,pid); return [dict(r) for r in c.execute("SELECT id AS event_id,type AS event_type,ts AS timestamp,actor,project_id,plan_v AS plan_version,run_id AS migration_run_id,details FROM audit WHERE project_id=? ORDER BY id",(pid,))]
def _demo_data():
    names=["Muskan","Arjun","Priya","Rohan","Sana","Vikram","Anita","Karan","Neha","Imran","Divya","Sameer","Leena","Tarun","Meera","Dev"]; act=["Y","yes","1","N","no","0","true","false"]; rs=[]
    for i,n in enumerate(names,1):
        rs.append({"customer_id":f"CUS-{i:03}","first_name":f"  {n}  " if i%4==0 else n,"last_name":"Singh","email":f"{n}@Example.com" if i%2 else f"{n.lower()}@example.com","phone":None if i==3 else "" if i==7 else f"98111{i:05}","dob":f"{i%27+1:02}/{i%12+1:02}/{1980+i}","gender":"MFU"[i%3],"active":act[i%8]})
    base={"first_name":"X","last_name":"Y","phone":"9","gender":"M","active":"Y","dob":"01/01/1990","email":"x@example.com","customer_id":"CUS-1xx"}
    return rs+[{**base,"customer_id":"CUS-103","email":"invalid-email"},{**base,"customer_id":"CUS-104","dob":"32/14/2024"},{**base,"customer_id":None},{**base,"customer_id":"CUS-106","gender":"Q"}]
def load_demo():
    p=create_project("Customer Migration Demo","customer_source","customer_target",50); pid=p["id"]
    set_schema(pid,"src",{k:{"type":"string"} for k in["customer_id","first_name","last_name","email","phone","dob","gender","active"]})
    set_schema(pid,"tgt",{"customerId":{"type":"string","required":True},"firstName":{"type":"string","required":True},"lastName":{"type":"string","required":True},"email":{"type":"string","format":"email","required":True},"phoneNumber":{"type":"string"},"birthDate":{"type":"date"},"gender":{"type":"enum","values":["MALE","FEMALE","UNKNOWN"]},"isActive":{"type":"boolean"}})
    set_samples(pid,_demo_data()); c=conn()
    c.execute("INSERT OR IGNORE INTO target(key,mig,run_id,rid,data) VALUES('SEED:EXT-001',NULL,NULL,'EXT-001','{}')"); c.commit(); return {"project_id":pid}
def reset_demo():
    c=conn()
    for t in["recons","rollbacks","target","runs","dry_runs","plans","audit","projects"]: c.execute(f"DROP TABLE IF EXISTS {t}")
    c.commit(); c.close(); return load_demo()
