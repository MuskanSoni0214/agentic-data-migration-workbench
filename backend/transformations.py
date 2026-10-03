"""Fixed transformation registry. No user-supplied code is ever executed."""
import datetime as dt
class TxError(ValueError): pass
DATE_FORMATS={"%d/%m/%Y","%m/%d/%Y","%Y-%m-%d","%d-%m-%Y"}
def _one(f): return lambda vals,p: [f(vals[0],p)]
def _date(v,p):
    if v in (None,""): return None
    fmt=p.get("input_format","%d/%m/%Y")
    try: return dt.datetime.strptime(str(v).strip(),fmt).date().isoformat()
    except ValueError: raise TxError(f'Cannot parse "{v}" as {fmt}')
def _int(v,p):
    if v in (None,""): return None
    try: return int(str(v).strip())
    except ValueError: raise TxError(f'Cannot convert "{v}" to integer')
def _bool(v,p):
    if v in (None,""): return None
    s=str(v).strip().lower()
    if s in("y","yes","true","t","1"): return True
    if s in("n","no","false","f","0"): return False
    raise TxError(f'Unrecognised boolean "{v}"')
def _enum(v,p):
    if v in (None,""): return None
    k=str(v).strip().upper()
    if k not in p["mapping"]: raise TxError(f'No enum mapping for "{v}"')
    return p["mapping"][k]
def _combine(vals,p):
    parts=[str(v).strip() for v in vals if v not in (None,"")]
    return [p.get("separator"," ").join(parts) if parts else None]
def _split(vals,p):
    v=vals[0]; n=p["_n_out"]
    if v in (None,""): return [None]*n
    parts=str(v).strip().split(p.get("separator"," "),n-1)
    return parts+[None]*(n-len(parts))
def _s(f): return lambda v,p: v if v is None else f(str(v))
REG={
 "rename":("Copy value unchanged","any","same",_one(lambda v,p:v)),
 "string_trim":("Trim whitespace","string","string",_one(_s(str.strip))),
 "string_lowercase":("Lowercase text","string","string",_one(_s(str.lower))),
 "string_uppercase":("Uppercase text","string","string",_one(_s(str.upper))),
 "date_format":("Parse a date (whitelisted input format) to ISO-8601","string","date",_one(_date)),
 "integer_to_string":("Integer to string","integer","string",_one(lambda v,p:None if v is None else str(v))),
 "string_to_integer":("String to integer","string","integer",_one(_int)),
 "boolean_normalization":("Y/yes/true/1 and N/no/false/0 to boolean","string","boolean",_one(_bool)),
 "null_to_default":("Replace null/empty with a default","any","same",_one(lambda v,p:p.get("default","") if v in (None,"") else v)),
 "enum_mapping":("Map source codes to target enum values","string","enum",_one(_enum)),
 "combine_fields":("Join 2+ source fields with a separator","string","string",_combine),
 "split_field":("Split one field into 2+ target fields","string","string",_split)}
def describe():
    return [{"name":k,"description":v[0],"input_type":v[1],"output_type":v[2],"multi_field":k in("combine_fields","split_field")} for k,v in REG.items()]
def check_params(name,p,n_in,n_out):
    if name not in REG: raise TxError(f"Unsupported transformation: {name}")
    p=p or {}
    if name=="enum_mapping" and not (isinstance(p.get("mapping"),dict) and p["mapping"]): raise TxError("enum_mapping requires a non-empty 'mapping' object")
    if name=="date_format" and p.get("input_format","%d/%m/%Y") not in DATE_FORMATS: raise TxError("input_format not in whitelist")
    if name=="combine_fields" and (n_in<2 or n_out!=1): raise TxError("combine_fields needs 2+ sources and 1 target")
    elif name=="split_field" and (n_in!=1 or n_out<2): raise TxError("split_field needs 1 source and 2+ targets")
    elif name not in("combine_fields","split_field") and (n_in!=1 or n_out!=1): raise TxError(f"{name} needs exactly 1 source and 1 target")
def apply(name,vals,p,n_out=1):
    p=dict(p or {}); p["_n_out"]=n_out; check_params(name,p,len(vals),n_out)
    return REG[name][3](vals,p)
def validate_mapping(m,src,tgt):
    e=[]; S,T=m.get("sources") or [],m.get("targets") or []
    if not S or not T: return ["Mapping needs at least one source and one target"]
    for f in S:
        if f not in src: e.append(f"Unknown source field: {f}")
    for f in T:
        if f not in tgt: e.append(f"Unknown target field: {f}")
    if e: return e
    try: check_params(m.get("transform"),m.get("params"),len(S),len(T))
    except TxError as x: return [str(x)]
    _,tin,tout,_f=REG[m["transform"]]
    for f in S:
        if tin not in("any",src[f]["type"]): e.append(f"{m['transform']} expects {tin} input but {f} is {src[f]['type']}")
    want=src[S[0]]["type"] if tout=="same" else tout
    for f in T:
        if tgt[f]["type"]!=want: e.append(f"Type mismatch: {m['transform']} yields {want}, target {f} is {tgt[f]['type']}")
    return e
def check_target(spec,v):
    if v is None or v=="": return ("REQUIRED_MISSING","Required target field is empty") if spec.get("required") else None
    t=spec["type"]
    if t=="string":
        if not isinstance(v,str): return ("TYPE_MISMATCH","Expected string")
        if spec.get("format")=="email":
            a,_,d=v.partition("@")
            if not a or "." not in d or " " in v or "@" in d: return ("INVALID_EMAIL","Not a valid email address")
        if spec.get("maxLength") and len(v)>spec["maxLength"]: return ("LENGTH_EXCEEDED",f"Longer than {spec['maxLength']}")
    if t=="integer" and (not isinstance(v,int) or isinstance(v,bool)): return ("TYPE_MISMATCH","Expected integer")
    if t=="boolean" and not isinstance(v,bool): return ("TYPE_MISMATCH","Expected boolean")
    if t=="date":
        try: dt.date.fromisoformat(v)
        except (ValueError,TypeError): return ("INVALID_DATE","Expected YYYY-MM-DD")
    if t=="enum" and v not in spec["values"]: return ("ENUM_VIOLATION","Not one of "+", ".join(spec["values"]))
    return None
