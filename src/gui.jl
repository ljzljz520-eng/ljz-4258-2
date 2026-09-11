# Gtk4 图形界面（headless 安全：GTK 初始化失败时给出明确提示并回退 CLI）。
# 工程边界：工程师确认稳定段/样品时延/罐持液/量程增益；程序只核算、展示与报告，
# 不提供标准化比例推荐，不含任何分离机控制按钮或写指令。

const GTK_REF = Ref{Module}()

"""GTK 是否真正可显示（无显示环境/初始化失败时为 false）。"""
function gtk_available()
    try
        m = Base.require(Main, :Gtk4)
        GTK_REF[] = m
        # 无显示环境时 Gtk4 自身会告警且 initialized 为 false
        if isdefined(m, :initialized) && m.initialized[] === false
            return false
        end
        # 尝试构造一个最小窗口进一步确认
        w = m.GtkWindow("probe", 100, 60)
        m.close(w)
        return true
    catch e
        @warn "Gtk4 不可用（可能无显示环境），使用 --cli 模式" exception=e
        return false
    end
end

function run_gui(; dbpath=joinpath(pwd(), "data", "milkbalance.duckdb"),
                 outdir=joinpath(pwd(), "data"))
    gtk_available() || error("GTK 不可用：请在桌面环境运行，或使用 --cli/--demo。")
    G = GTK_REF[]

    win = G.GtkWindow("原奶分离-乳脂回配 核算（不含标准化推荐/分离机控制）", 1080, 760)
    box = G.GtkBox(:v); win[] = box

    topbar = G.GtkBox(:h); push!(box, topbar)
    push!(topbar, G.GtkLabel("测试情景："))
    combo = G.GtkDropDown(["S1 奶油量程切换", "S2 脱脂乳样晚到",
                           "S3 回流跨批", "S4 罐底旧料未登记", "S5 干湿基混淆",
                           "S6 非稳态取样(仪)", "S7 清洗后保持旧值(仪)",
                           "S8 单点超量程(仪)", "S9 温度补偿版本改变(仪)",
                           "S10 一样跨两流量段(仪)"])
    push!(topbar, combo)

    stable_cb = G.GtkCheckButton("工程师确认稳定段")
    push!(topbar, stable_cb)

    gain_entry = G.GtkEntry()
    push!(topbar, gain_entry)
    G.GtkEditable.set_text(gain_entry, "")

    calc_btn = G.GtkButton("计算闭合")
    plot_btn = G.GtkButton("打开 Plotly 图（HTML）")
    push!(topbar, calc_btn, plot_btn)

    nb = G.GtkNotebook(); push!(box, nb)
    report_buf = G.GtkTextBuffer()
    topo_buf = G.GtkTextBuffer()
    flags_buf = G.GtkTextBuffer()
    for (buf, lbl) in ((report_buf, "核算结果"), (topo_buf, "流程拓扑(DuckDB)"),
                       (flags_buf, "标记与未计物流"))
        v = G.GtkTextView()
        G.G_.set_buffer(v, buf)
        sw = G.GtkScrolledWindow(); sw[] = v
        G.push!(nb, sw, G.GtkLabel(lbl))
    end

    status = G.GtkLabel("就绪。选择情景后点击“计算闭合”。S1 量程2增益修正可在文本框填入（如 0.08）。")
    push!(box, status)

    current_id() = ["S1", "S2", "S3", "S4", "S5",
                    "S6", "S7", "S8", "S9", "S10"][G.G_.get_selected(combo) + 1]

    function build_scenario(id)
        sc = scenario(id)
        stable = G.G_.get_active(stable_cb)
        gains = Dict{Tuple{String,Int},Float64}()
        gt = strip(G.GtkEditable.get_text(gain_entry))
        if id == "S1" && gt != ""
            gv = tryparse(Float64, gt)
            if gv === nothing
                G.G_.set_text(status, "增益修正需为小数，如 0.08")
                return sc
            end
            gains[("cream", 2)] = gv
        end
        e = sc.engineer
        return SetfieldCompat_set_engineer(sc, EngineerInputs(
            stable, e.sample_delay_ok, e.holdups, gains))
    end

    plot_path = Ref("")
    G.signal_connect(calc_btn, "clicked") do _
        try
            id = current_id()
            sc = build_scenario(id)
            mkpath(dirname(dbpath)); mkpath(outdir)
            db = open_db(dbpath)
            try
                paths = persist_mirror(sc, outdir)
                apaths = persist_analyzer(sc, outdir)
                save_scenario(db, shim_batch(sc), paths; analyzer_paths=apaths)
                rep = reconcile(sc)
                save_report(db, shim_batch(sc), rep)
                review = review_analyzers(sc)
                save_review(db, shim_batch(sc), review)
                G.G_.set_text(report_buf,
                              text_report(sc, rep) * analyzer_review_text(review))
                G.G_.set_text(topo_buf, topology_text(sc))
                G.G_.set_text(flags_buf, flags_text(rep))
                pp = joinpath(outdir, "plot_" * sc.spec.batch_id * ".html")
                write_plot_html(pp, rep; title=sc.title, review=review)
                plot_path[] = pp
                G.G_.set_text(status, "已写入 DuckDB：$dbpath ；图：$pp")
            finally
                DuckDB.DBInterface.close!(db)
            end
        catch ex
            G.G_.set_text(status, "计算失败：" * sprint(showerror, ex))
        end
    end

    G.signal_connect(plot_btn, "clicked") do _
        if plot_path[] == ""
            G.G_.set_text(status, "请先计算闭合。")
        else
            open_in_browser(plot_path[])
            G.G_.set_text(status, "已尝试打开：" * plot_path[])
        end
    end

    show(win)
    return win
end

# 避免额外依赖 ConstructionBases/Setfields：直接重建情景（保留分析仪数据）
function SetfieldCompat_set_engineer(sc::Scenario, e::EngineerInputs)
    return Scenario(; id=sc.id, title=sc.title, spec=sc.spec, nodes=sc.nodes,
                    streams=sc.streams, meters=sc.meters, mirror=sc.mirror,
                    samples=sc.samples, engineer=e, reflux_kg=sc.reflux_kg,
                    reflux_cross=sc.reflux_cross, expect_flags=sc.expect_flags,
                    analyzer_readings=sc.analyzer_readings,
                    analyzer_specs=sc.analyzer_specs,
                    expect_review_flags=sc.expect_review_flags)
end
shim_batch(sc) = sc

function topology_text(sc)
    io = IOBuffer()
    println(io, "节点（nodes 表）：")
    for n in sc.nodes
        @printf(io, "  %-9s %-12s %s\n", n.id, n.name, n.kind)
    end
    println(io, "\n支路（streams 表，src → dst）：")
    for s in sc.streams
        tags = String[]
        s.external_in && push!(tags, "外部输入")
        s.external_out && push!(tags, "外部输出")
        s.is_reflux && push!(tags, "回流")
        s.crosses_batch && push!(tags, "跨批")
        @printf(io, "  %-8s %s → %s  [%s]\n", s.id, s.src, s.dst, join(tags, ","))
    end
    println(io, "\n现场流量/密度镜像先转 Apache Arrow 表；")
    println(io, "流程拓扑、计算窗口、样品索引与核算结果写入 DuckDB。")
    String(take!(io))
end

flags_text(rep) = begin
    io = IOBuffer()
    println(io, "数据质量标记（级别）：")
    isempty(rep.flags) && println(io, "  无")
    for f in rep.flags
        @printf(io, "  [%s] %s\n", flag_level(f), explain_flag(f))
    end
    println(io, "\n未计物流：", isempty(rep.missing_streams) ? "无" :
            join(rep.missing_streams, ", "))
    println(io, "实际脂肪区间(湿基)：", fmtpct(rep.actual_fat_interval))
    String(take!(io))
end

function open_in_browser(path)
    try
        if Sys.islinux()
            run(pipeline(`xdg-open $path`; stdout=devnull, stderr=devnull); wait=false)
        elseif Sys.isapple()
            run(pipeline(`open $path`; wait=false))
        else
            run(pipeline(`cmd /c start $path`; wait=false))
        end
    catch
        @info "请手动在浏览器打开 $path"
    end
end
