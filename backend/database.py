import os, sqlite3, json, datetime
dumps=lambda o: json.dumps(o,sort_keys=True,separators=(",",":"))
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
SCHEMA="""
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL,source_name TEXT,target_name TEXT,src TEXT,tgt TEXT,recs TEXT,qs TEXT DEFAULT '[]',max_n INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),v INTEGER NOT NULL,approved INTEGER DEFAULT 0,maps TEXT,risks TEXT,approval TEXT,note TEXT,UNIQUE(project_id,v));
CREATE TABLE IF NOT EXISTS dry_runs(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),plan_id INTEGER NOT NULL REFERENCES plans(id),plan_v INTEGER,result TEXT,hash TEXT,ts TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL,plan_id INTEGER NOT NULL REFERENCES plans(id),plan_v INTEGER,dry_id INTEGER REFERENCES dry_runs(id),mig TEXT,processed INTEGER,inserted INTEGER,skipped INTEGER,failed INTEGER,rolled INTEGER DEFAULT 0,ts TEXT);
CREATE TABLE IF NOT EXISTS target(key TEXT PRIMARY KEY,mig TEXT,run_id INTEGER REFERENCES runs(id),rid TEXT,data TEXT);
CREATE TABLE IF NOT EXISTS recons(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL REFERENCES runs(id),result TEXT,ts TEXT);
CREATE TABLE IF NOT EXISTS rollbacks(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL REFERENCES runs(id),performed_by TEXT,performed_at TEXT,records_rolled_back INTEGER,status TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,ts TEXT,type TEXT,project_id INTEGER,plan_v INTEGER,run_id INTEGER,actor TEXT,details TEXT);
CREATE INDEX IF NOT EXISTS ix_audit_p ON audit(project_id);
CREATE INDEX IF NOT EXISTS ix_tgt_run ON target(run_id);
CREATE INDEX IF NOT EXISTS ix_dry_plan ON dry_runs(plan_id);
CREATE TRIGGER IF NOT EXISTS audit_nu BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS plan_imm BEFORE UPDATE OF maps,risks ON plans WHEN OLD.approved=1 BEGIN SELECT RAISE(ABORT,'approved plan is immutable'); END;
"""
def conn():
    c=sqlite3.connect(os.environ.get("DATABASE_URL","sqlite:///./migration.db").replace("sqlite:///",""))
    c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); c.executescript(SCHEMA)
    if "analysis" not in [r[1] for r in c.execute("PRAGMA table_info(plans)")]: c.execute("ALTER TABLE plans ADD COLUMN analysis TEXT")
    return c
