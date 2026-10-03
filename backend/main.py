import os
from typing import Any, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from . import services as S, transformations as T
app=FastAPI(title="Migration Workbench API",version="2.0.0")
origins=[o for o in os.environ.get("CORS_ALLOWED_ORIGINS","").split(",") if o]
if origins: app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=["*"],allow_headers=["*"])
@app.exception_handler(S.ApiError)
async def _e(_:Request,e:S.ApiError): return JSONResponse({"detail":e.msg},status_code=e.status)
class ProjectIn(BaseModel): name:str; source_name:str="source"; target_name:str="target"; max_sample_size:Optional[int]=None
class SamplesIn(BaseModel): records:list[dict[str,Any]]
class MapIn(BaseModel): sources:list[str]; targets:list[str]; transform:str; params:dict[str,Any]={}; status:str="ACCEPTED"; confidence:str="HIGH"; reason:str=""; risk:str="LOW"
class MapsIn(BaseModel): mappings:list[dict[str,Any]]
class ApproveIn(BaseModel): approved_by:str="demo.user"; confirm:bool=False
class ExecIn(BaseModel): dry_run_id:int; confirm:bool=False
class ConfirmIn(BaseModel): confirm:bool=False
class StatusIn(BaseModel): status:str; answer:Optional[str]=None
a="/api"
@app.post(a+"/projects",status_code=201)
def p1(b:ProjectIn): return S.create_project(b.name,b.source_name,b.target_name,b.max_sample_size)
@app.get(a+"/projects")
def p2(): return S.list_projects()
@app.get(a+"/projects/{pid}")
def p3(pid:int): return S.proj(S.conn(),pid)
@app.post(a+"/projects/{pid}/source-schema")
def p4(pid:int,b:dict[str,Any]): return S.set_schema(pid,"src",b)
@app.post(a+"/projects/{pid}/target-schema")
def p5(pid:int,b:dict[str,Any]): return S.set_schema(pid,"tgt",b)
@app.post(a+"/projects/{pid}/sample-records")
def p6(pid:int,b:SamplesIn): return {"count":S.set_samples(pid,b.records)}
@app.get(a+"/transformations")
def t1(): return T.describe()
@app.post(a+"/projects/{pid}/analyze")
def an(pid:int): return S.analyze(pid)
@app.get(a+"/projects/{pid}/plans")
def pl(pid:int): return S.list_plans(pid)
@app.get(a+"/plans/{id}")
def pg(id:int): return S.get_plan(id)
@app.put(a+"/plans/{id}/mappings")
def pm(id:int,b:MapsIn): return S.update_mappings(id,b.mappings)
@app.post(a+"/plans/{id}/mappings",status_code=201)
def pa(id:int,b:MapIn): return S.add_mapping(id,b.model_dump())
@app.post(a+"/plans/{id}/risks/{rid}")
def pr(id:int,rid:int,b:StatusIn): return S.set_risk(id,rid,b.status)
@app.post(a+"/projects/{pid}/questions/{qid}")
def pq(pid:int,qid:int,b:StatusIn): return S.set_question(pid,qid,b.status,b.answer)
@app.post(a+"/plans/{id}/approve")
def ap(id:int,b:ApproveIn): return S.approve(id,b.approved_by,b.confirm)
@app.get(a+"/plans/{x}/compare/{y}")
def cp(x:int,y:int): return S.compare(x,y)
@app.post(a+"/plans/{id}/dry-run",status_code=201)
def dr(id:int): return S.dry_run(id)
@app.get(a+"/dry-runs/{id}")
def dg(id:int): return S.dry_get(id)
@app.get(a+"/dry-runs/{id}/records")
def dq(id:int,status:Optional[str]=None): return S.dry_records(id,status)
@app.get(a+"/projects/{pid}/quarantine")
def qu(pid:int,field:Optional[str]=None,code:Optional[str]=None,plan_version:Optional[int]=None,record_id:Optional[str]=None): return S.quarantine(pid,field,code,plan_version,record_id)
@app.post(a+"/plans/{id}/execute",status_code=201)
def ex(id:int,b:ExecIn): return S.execute(id,b.dry_run_id,b.confirm)
@app.get(a+"/migration-runs/{id}")
def rg(id:int): return S.run_get(id)
@app.get(a+"/target-records")
def tr(): return S.target_rows()
@app.post(a+"/migration-runs/{id}/reconcile")
def rc(id:int): return S.reconcile(id)
@app.get(a+"/migration-runs/{id}/reconciliation")
def rr(id:int): return S.recon_get(id)
@app.post(a+"/migration-runs/{id}/rollback")
def rb(id:int,b:ConfirmIn): return S.rollback(id,b.confirm)
@app.get(a+"/projects/{pid}/history")
def hs(pid:int): return S.history(pid)
@app.get(a+"/projects/{pid}/dry-runs")
def dl(pid:int): return S.list_dry_runs(pid)
@app.get(a+"/projects/{pid}/migration-runs")
def rl(pid:int): return S.list_runs(pid)
@app.get(a+"/status")
def st(): return {"api":"connected","database":"SQLite","ai_mode":"Mock" if os.environ.get("MOCK_AI","true").lower()=="true" else "LLM (provider not implemented)","sample_limit":int(os.environ.get("MAX_SAMPLE_SIZE","50")),"source":1,"target":1}
@app.post(a+"/demo",status_code=201)
def d1(): return S.load_demo()
@app.post(a+"/demo/reset",status_code=201)
def d2(): return S.reset_demo()
if os.path.isdir("frontend"): app.mount("/",StaticFiles(directory="frontend",html=True),name="ui")
