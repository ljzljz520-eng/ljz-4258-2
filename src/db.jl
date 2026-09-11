# DuckDB 持久化：流程拓扑、计算窗口、样品索引、核算结果、闭合结论。
# 现场镜像先转 Arrow 表，再尝试注册为 DuckDB 视图供查询（失败回退逐行写入）。
using DuckDB
using DataFrames

const SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id VARCHAR, batch_id VARCHAR, name VARCHAR, kind VARCHAR);
CREATE TABLE IF NOT EXISTS streams (
    id VARCHAR, batch_id VARCHAR, name VARCHAR, src VARCHAR, dst VARCHAR,
    external_in BOOLEAN, external_out BOOLEAN, is_reflux BOOLEAN, crosses_batch BOOLEAN);
CREATE TABLE IF NOT EXISTS meters (
    stream_id VARCHAR, batch_id VARCHAR, ranges VARCHAR,
    base_rel DOUBLE, gain_rel DOUBLE);
CREATE TABLE IF NOT EXISTS windows (
    batch_id VARCHAR PRIMARY KEY, t0 DOUBLE, t1 DOUBLE,
    stable0 DOUBLE, stable1 DOUBLE, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS samples (
    id VARCHAR, batch_id VARCHAR, stream_id VARCHAR, taken_at DOUBLE,
    received_at DOUBLE, fat DOUBLE, solids DOUBLE, basis VARCHAR, delay_ok BOOLEAN);
CREATE TABLE IF NOT EXISTS mirror_index (
    batch_id VARCHAR, stream_id VARCHAR, n_rows BIGINT,
    arrow_path VARCHAR, t_min DOUBLE, t_max DOUBLE);
CREATE TABLE IF NOT EXISTS holdups (
    batch_id VARCHAR, tank_id VARCHAR, start_kg DOUBLE, end_kg DOUBLE,
    registered BOOLEAN, fat_start DOUBLE, fat_end DOUBLE,
    solids_start DOUBLE, solids_end DOUBLE);
CREATE TABLE IF NOT EXISTS branches (
    batch_id VARCHAR, stream_id VARCHAR, mass_x DOUBLE, mass_u DOUBLE,
    fat_x DOUBLE, fat_u DOUBLE, solids_x DOUBLE, solids_u DOUBLE,
    coverage DOUBLE, switched BOOLEAN);
CREATE TABLE IF NOT EXISTS closures (
    batch_id VARCHAR, node_id VARCHAR, label VARCHAR,
    res_mass_x DOUBLE, res_mass_u DOUBLE, status_mass VARCHAR,
    res_fat_x DOUBLE, res_fat_u DOUBLE, status_fat VARCHAR,
    res_solids_x DOUBLE, res_solids_u DOUBLE, status_solids VARCHAR);
CREATE TABLE IF NOT EXISTS flags (
    batch_id VARCHAR, flag VARCHAR, level VARCHAR);
CREATE TABLE IF NOT EXISTS analyzer_index (
    batch_id VARCHAR, stream_id VARCHAR, n_rows BIGINT,
    arrow_path VARCHAR, t_min DOUBLE, t_max DOUBLE);
CREATE TABLE IF NOT EXISTS analyzer_points (
    batch_id VARCHAR, stream_id VARCHAR, sample_id VARCHAR,
    taken_at DOUBLE, analyzer_t DOUBLE, online_fat DOUBLE, lab_fat DOUBLE,
    deviation DOUBLE, used BOOLEAN, reasons VARCHAR, tcomp_version INTEGER);
CREATE TABLE IF NOT EXISTS analyzer_status (
    batch_id VARCHAR, stream_id VARCHAR, n_used BIGINT, mean_dev DOUBLE,
    slope_per_h DOUBLE, status VARCHAR, tcomp_versions VARCHAR);
"""

sql_escape(s::AbstractString) = replace(s, "'" => "''")

function open_db(path::AbstractString)
    db = DuckDB.DBInterface.connect(DuckDB.DB, path)
    for stmt in split(SCHEMA, ';'; keepempty=false)
        s = strip(stmt)
        isempty(s) || DuckDB.DBInterface.execute(db, s)
    end
    return db
end

clear_batch(db, batch) =
    for t in ("nodes","streams","meters","windows","samples","mirror_index",
              "holdups","branches","closures","flags",
              "analyzer_index","analyzer_points","analyzer_status")
        DuckDB.DBInterface.execute(db,
            "DELETE FROM $t WHERE batch_id = '$(sql_escape(batch))'")
    end

qbool(b) = b ? "TRUE" : "FALSE"

function save_scenario(db, sc::Scenario, arrow_paths::Dict{String,String}=Dict();
                       analyzer_paths::Dict{String,String}=Dict())
    clear_batch(db, sc.spec.batch_id)
    b = sql_escape(sc.spec.batch_id)
    for n in sc.nodes
        DuckDB.DBInterface.execute(db,
            "INSERT INTO nodes VALUES ('$(sql_escape(n.id))','$b','$(sql_escape(n.name))','$(string(n.kind))')")
    end
    for s in sc.streams
        DuckDB.DBInterface.execute(db, """
            INSERT INTO streams VALUES ('$(sql_escape(s.id))','$b','$(sql_escape(s.name))',
            '$(sql_escape(s.src))','$(sql_escape(s.dst))',
            $(qbool(s.external_in)),$(qbool(s.external_out)),
            $(qbool(s.is_reflux)),$(qbool(s.crosses_batch)))""")
    end
    for m in sc.meters
        rngs = join(("[$(lo_),$(hi_)]" for (lo_, hi_) in m.ranges), ";")
        DuckDB.DBInterface.execute(db,
            "INSERT INTO meters VALUES ('$(sql_escape(m.stream_id))','$b','$rngs',$(m.base_rel),$(m.gain_rel))")
    end
    DuckDB.DBInterface.execute(db, """
        INSERT INTO windows VALUES ('$b',$(sc.spec.t0),$(sc.spec.t1),
        $(sc.spec.stable0),$(sc.spec.stable1), now())""")
    for x in sc.samples
        DuckDB.DBInterface.execute(db, """
            INSERT INTO samples VALUES ('$(sql_escape(x.id))','$b','$(sql_escape(x.stream_id))',
            $(x.taken_at),$(x.received_at),$(x.fat),$(x.solids),
            '$(x.basis == wet ? "wet" : "dry")',$(qbool(x.delay_ok)))""")
    end
    for h in sc.engineer.holdups
        DuckDB.DBInterface.execute(db, """
            INSERT INTO holdups VALUES ('$b','$(sql_escape(h.tank_id))',
            $(h.start_kg),$(h.end_kg),$(qbool(h.registered)),
            $(h.fat_start),$(h.fat_end),$(h.solids_start),$(h.solids_end))""")
    end
    for (sid, path) in arrow_paths
        sub = filter(r -> r.stream_id == sid, sc.mirror)
        isempty(sub) && continue
        DuckDB.DBInterface.execute(db, """
            INSERT INTO mirror_index VALUES ('$b','$(sql_escape(sid))',$(length(sub)),
            '$(sql_escape(path))',$(sub[1].t),$(sub[end].t))""")
    end
    for (sid, path) in analyzer_paths
        sub = filter(r -> r.stream_id == sid, sc.analyzer_readings)
        isempty(sub) && continue
        DuckDB.DBInterface.execute(db, """
            INSERT INTO analyzer_index VALUES ('$b','$(sql_escape(sid))',$(length(sub)),
            '$(sql_escape(path))',$(sub[1].t),$(sub[end].t))""")
    end
    return nothing
end

function save_report(db, sc::Scenario, rep::WindowReport)
    b = sql_escape(sc.spec.batch_id)
    DuckDB.DBInterface.execute(db, "DELETE FROM branches WHERE batch_id='$b'")
    DuckDB.DBInterface.execute(db, "DELETE FROM closures WHERE batch_id='$b'")
    DuckDB.DBInterface.execute(db, "DELETE FROM flags WHERE batch_id='$b'")
    fnum(x) = isnan(x) ? "NULL" : string(x)
    for x in rep.branches
        DuckDB.DBInterface.execute(db, """
            INSERT INTO branches VALUES ('$b','$(sql_escape(x.stream_id))',
            $(fnum(x.mass.x)),$(fnum(x.mass.u)),$(fnum(x.fat.x)),$(fnum(x.fat.u)),
            $(fnum(x.solids.x)),$(fnum(x.solids.u)),$(x.coverage),$(qbool(x.switched)))""")
    end
    for c in vcat(rep.nodes, [rep.total])
        DuckDB.DBInterface.execute(db, """
            INSERT INTO closures VALUES ('$b','$(sql_escape(c.node_id))','$(sql_escape(c.label))',
            $(fnum(c.residual_mass.x)),$(fnum(c.residual_mass.u)),'$(string(c.status_mass))',
            $(fnum(c.residual_fat.x)),$(fnum(c.residual_fat.u)),'$(string(c.status_fat))',
            $(fnum(c.residual_solids.x)),$(fnum(c.residual_solids.u)),'$(string(c.status_solids))')""")
    end
    for f in rep.flags
        DuckDB.DBInterface.execute(db,
            "INSERT INTO flags VALUES ('$b','$(sql_escape(f))','$(flag_level(f))')")
    end
    return nothing
end

"""保存在线脂肪仪偏差复核结果（匹配点 + 校准状态）。
复核结论与物料闭合分列存储；在线原始读数只在 Arrow 镜像中，不被修改。"""
function save_review(db, sc::Scenario, rev::AnalyzerReview)
    b = sql_escape(sc.spec.batch_id)
    DuckDB.DBInterface.execute(db, "DELETE FROM analyzer_points WHERE batch_id='$b'")
    DuckDB.DBInterface.execute(db, "DELETE FROM analyzer_status WHERE batch_id='$b'")
    fnum(x) = isnan(x) ? "NULL" : string(x)
    for sr in rev.streams
        for p in sr.points
            DuckDB.DBInterface.execute(db, """
                INSERT INTO analyzer_points VALUES ('$b','$(sql_escape(p.stream_id))',
                '$(sql_escape(p.sample_id))',$(p.taken_at),$(p.analyzer_t),
                $(fnum(p.online_fat)),$(fnum(p.lab_fat)),$(fnum(p.deviation)),
                $(qbool(p.used)),'$(sql_escape(join(p.reasons, ";")))',
                $(p.tcomp_version))""")
        end
        DuckDB.DBInterface.execute(db, """
            INSERT INTO analyzer_status VALUES ('$b','$(sql_escape(sr.stream_id))',
            $(sr.n_used),$(fnum(sr.mean_dev)),$(fnum(sr.slope_per_h)),
            '$(string(sr.status))','$(join(sr.tcomp_versions, ","))')""")
    end
    return nothing
end

"""把 Apache Arrow 表登记为 DuckDB 可 SQL 查询的关系（体现“镜像先转 Arrow 表”）。
优先 read_arrow 文件函数；版本不支持时读入 Arrow 表后注册 DataFrame；
仍失败则返回 Arrow 帧本身。"""
function register_arrow(db, arrow_path::AbstractString, view::AbstractString)
    # 路径1：DuckDB 原生 read_arrow（较新版本）
    try
        DuckDB.DBInterface.execute(db,
            "CREATE OR REPLACE VIEW $view AS SELECT * FROM read_arrow('$(sql_escape(arrow_path))')")
        return DataFrame(DuckDB.DBInterface.execute(db, "SELECT count(*) AS n FROM $view"))
    catch
    end
    # 路径2：先读成 Apache Arrow 表，再经 Arrow→DataFrame 注册为关系
    try
        tbl = Arrow.Table(arrow_path)              # 真正的 Arrow 表
        df = DataFrame(tbl)
        try
            DuckDB.register_data_frame(db, df, view)
        catch
            DuckDB.register_table(db, df, view)
        end
        return DataFrame(DuckDB.DBInterface.execute(db, "SELECT count(*) AS n FROM $view"))
    catch e
        @warn "Arrow 关系注册失败，回退到本地读取 Arrow 帧" exception=e
        return read_arrow(arrow_path)
    end
end

list_batches(db) =
    DataFrame(DuckDB.DBInterface.execute(db, "SELECT * FROM windows ORDER BY batch_id"))
