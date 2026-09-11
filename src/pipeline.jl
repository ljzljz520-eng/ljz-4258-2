# 端到端管线：情景 -> Arrow 镜像 -> DuckDB -> 核算 -> Plotly/文本报告。

"""把每个支路的现场镜像分别写成 Arrow IPC 文件（“先转 Apache Arrow 表”）。"""
function persist_mirror(sc::Scenario, outdir::AbstractString)
    mkpath(outdir)
    paths = Dict{String,String}()
    adir = joinpath(outdir, "arrow", sc.spec.batch_id)
    mkpath(adir)
    for sid in unique(s.id for s in sc.streams)
        rows = filter(r -> r.stream_id == sid, sc.mirror)
        isempty(rows) && continue
        df = mirror_to_frame(rows)
        p = joinpath(adir, sid * ".arrow")
        write_arrow(p, df)
        paths[sid] = p
    end
    # 样品索引同样落 Arrow（与 DuckDB samples 表对应）
    sp = joinpath(adir, "samples.arrow")
    write_arrow(sp, samples_to_frame(sc.samples))
    return paths
end

"""完整跑一个情景：持久化、核算、出图，返回 (scenario, report, text, html)。
可传入已打开的 db 连接（多个情景共用一个 DuckDB 文件时必须如此）；
不传则按 dbpath 临时打开并在结束后关闭。"""
function run_scenario(id::AbstractString;
                      dbpath=joinpath(pwd(), "data", "milkbalance.duckdb"),
                      outdir=joinpath(pwd(), "data"),
                      db=nothing,
                      gain_correction::Union{Nothing,Real}=nothing,
                      engineer_override::Union{Nothing,EngineerInputs}=nothing)
    sc = scenario(id)
    if engineer_override !== nothing
        sc = Scenario(sc.id, sc.title, sc.spec, sc.nodes, sc.streams, sc.meters,
                      sc.mirror, sc.samples, engineer_override,
                      sc.reflux_kg, sc.reflux_cross, sc.expect_flags)
    elseif gain_correction !== nothing
        e = sc.engineer
        gains = copy(e.range_gains)
        gains[("cream", 2)] = Float64(gain_correction)
        sc = Scenario(sc.id, sc.title, sc.spec, sc.nodes, sc.streams, sc.meters,
                      sc.mirror, sc.samples,
                      EngineerInputs(e.stable_confirmed, e.sample_delay_ok,
                                     e.holdups, gains),
                      sc.reflux_kg, sc.reflux_cross, sc.expect_flags)
    end

    mkpath(dirname(dbpath)); mkpath(outdir)
    own_db = db === nothing
    conn = own_db ? open_db(dbpath) : db
    local rep, txt, html
    try
        paths = persist_mirror(sc, outdir)
        save_scenario(conn, sc, paths)
        rep = reconcile(sc)
        save_report(conn, sc, rep)
        html = joinpath(outdir, "plot_" * sc.spec.batch_id * ".html")
        write_plot_html(html, rep; title=sc.title)
        txt = text_report(sc, rep)
    finally
        own_db && DuckDB.DBInterface.close!(conn)
    end
    return (scenario=sc, report=rep, text=txt, html=html)
end

"""验证一个情景的实际标记是否覆盖期望标记。"""
function expect_flags_present(rep::WindowReport, expects::Vector{String})
    present = Set(split(f, ':')[1] for f in rep.flags)
    missing_ = [e for e in expects if !(e in present)]
    return isempty(missing_), missing_, sort(collect(present))
end
