"""Planning agent. The agent receives only AgentTools: read-only inspection/validation.
There is deliberately no execute/insert/rollback tool anywhere in this module."""
import os
from abc import ABC, abstractmethod
from . import transformations as T
class AgentTools:
    def __init__(s,src,tgt,recs): s._src,s._tgt,s._recs=src,tgt,recs
    def inspect_source_schema(s): return dict(s._src)
    def inspect_target_schema(s): return dict(s._tgt)
    def inspect_sample_records(s): return list(s._recs)
    def list_supported_transformations(s): return T.describe()
    def validate_mapping(s,m): return T.validate_mapping(m,s._src,s._tgt)
    def validate_transformation(s,name,params=None,n_in=1,n_out=1):
        try: T.check_params(name,params,n_in,n_out); return []
        except T.TxError as x: return [str(x)]
    def generate_migration_plan(s,a):
        checked=[(m,s.validate_mapping(m)) for m in a["mappings"]]
        a["mappings"]=[m for m,e in checked if not e]
        a["incompatible_fields"]+=[{"sources":m["sources"],"errors":e} for m,e in checked if e]
        return a
class MigrationPlanningAgent(ABC):
    @abstractmethod
    def analyze(self,tools): ...
SYN={"phone":"phoneNumber","dob":"birthDate","active":"isActive"}
class MockMigrationPlanningAgent(MigrationPlanningAgent):
    def analyze(self,t):
        src,tgt,recs=t.inspect_source_schema(),t.inspect_target_schema(),t.inspect_sample_records()
        norm=lambda s:s.replace("_","").lower(); used=set(); maps=[]; risks=[]; sug=[]; qs=[]
        def risk(f,sev,d,imp,rec): risks.append({"field":f,"severity":sev,"description":d,"impact":imp,"recommendation":rec,"status":"OPEN"})
        for s in src:
            tn=next((x for x in tgt if norm(x)==norm(s)),None); conf="HIGH"; why="Naming similarity"
            if not tn and SYN.get(s) in tgt: tn=SYN[s]; conf="MEDIUM"; why="Semantic similarity (alias/abbreviation)"
            if not tn:
                risk(s,"LOW","No matching target field","Source data not migrated","Map manually or leave unmapped"); continue
            used.add(tn); tt=tgt[tn]["type"]; tr="rename"; p={}; sev="LOW"
            if tt=="date": tr,sev,p="date_format","HIGH",{"input_format":"%d/%m/%Y"}; why+=". Source is DD/MM/YYYY; target requires ISO-8601"
            elif tt=="enum": tr,sev,conf,p="enum_mapping","MEDIUM","MEDIUM",{"mapping":{"M":"MALE","F":"FEMALE","U":"UNKNOWN"}}; why+=". Codes must be mapped to enum values"
            elif tt=="boolean": tr,sev="boolean_normalization","MEDIUM"; why+=". Strings must be normalised to boolean"
            elif tgt[tn].get("format")=="email": tr="string_lowercase"
            elif tn in("firstName","lastName"): tr="string_trim"
            if tgt[tn].get("required") and any(r.get(s) in (None,"") for r in recs): sev="HIGH"; why+=". Required target but samples contain nulls"
            maps.append({"sources":[s],"targets":[tn],"transform":tr,"params":p,"confidence":conf,"reason":why,"risk":sev,"status":"SUGGESTED","source_field":s,"target_field":tn,"source_type":src[s]["type"],"target_type":tt})
            if tr!="rename": sug.append({"source":s,"target":tn,"transformation":tr})
            if sev!="LOW": risk(f"{s} -> {tn}",sev,why,"Records rejected or values altered",f"Apply {tr} and confirm")
        missing=[x for x in tgt if x not in used]
        for x in missing:
            if tgt[x].get("required"): risk(x,"HIGH","Required target field has no source","All records fail","Add a mapping")
        nul=sum(r.get("customer_id") in (None,"") for r in recs)
        if nul: qs.append((f"Required target customerId has {nul} null source ID(s). Quarantine them?","Required-field conflict",["customer_id"]))
        em=next((m for m in maps if m["transform"]=="enum_mapping"),None)
        if em:
            f=em["sources"][0]; odd=sorted({r[f] for r in recs if r.get(f) and str(r[f]).upper() not in em["params"]["mapping"]})
            if odd: qs.append((f"Values {odd} in {f} are not in the M/F/U mapping. Map to UNKNOWN or quarantine?","Enum incompatibility",[f]))
        ph=sum(r.get("phone") in (None,"") for r in recs)
        if ph: qs.append((f"{ph} record(s) have no phone. Store NULL or empty string?","Nullable handling",["phone"]))
        if any(m["transform"]=="date_format" for m in maps): qs.append(("Confirm dob is always DD/MM/YYYY, never MM/DD/YYYY.","Ambiguous date format",["dob"]))
        return t.generate_migration_plan({"mappings":maps,"missing_fields":missing,"incompatible_fields":[],"suggested_transformations":sug,"risks":risks,"clarification_questions":[{"question":q,"reason":r,"affected_fields":a} for q,r,a in qs]})
class LLMMigrationPlanningAgent(MigrationPlanningAgent):
    def analyze(self,tools): raise NotImplementedError("LLM provider not implemented in this build; set MOCK_AI=true")
def get_agent():
    return MockMigrationPlanningAgent() if os.environ.get("MOCK_AI","true").lower()=="true" else LLMMigrationPlanningAgent()
