using Test
using MilkBalance
using MilkBalance: T1, TRUE_FLOW, default_holdups, default_engineer, scenario, Scenario
using DataFrames

# 临时输出目录
const TMP = mktempdir()

flags_of(rep) = Set(split(f, ':')[1] for f in rep.flags)
st(rep, node, kind) =
    getproperty(rep.nodes[findfirst(n -> n.node_id == node, rep.nodes)], kind)

@testset "MilkBalance 区间运算" begin
    a = IV(100.0, 2.0); b = IV(30.0, 1.0)
    @test (a - b).x == 70.0
    @test (a - b).u ≈ sqrt(5)
    @test contains0(IV(1.0, 2.0))
    @test !contains0(IV(5.0, 2.0))
    c = MilkBalance.compmass(a, IV(0.04, 0.0005))
    @test c.x == 4.0
    @test c.u ≈ sqrt((100*0.0005)^2 + (0.04*2.0)^2)
end

@testset "共同窗口：基线真值闭合（S3 跨批亦闭合）" begin
    for id in ("S3",)
        r = MilkBalance.run_scenario(id; outdir=TMP,
                                     dbpath=joinpath(TMP, "t.duckdb"))
        rep = r.report
        for n in rep.nodes
            @test n.status_mass === MilkBalance.closed
            @test n.status_fat === MilkBalance.closed
            @test n.status_solids === MilkBalance.closed
        end
        @test rep.total.status_mass === MilkBalance.closed
        @test rep.total.status_fat === MilkBalance.closed
        @test rep.total.status_solids === MilkBalance.closed
        @test abs(rep.total.residual_mass.x) < 12.0
        @test abs(rep.total.residual_fat.x) < 3.0
        # 实际产品组成区间覆盖真值
        @test rep.actual_fat_interval.x ≈ 0.03524 atol=0.0005
        @test contains0(IV(rep.actual_fat_interval.x - 0.03524, rep.actual_fat_interval.u))
    end
end

@testset "S1 奶油量程切换：未确认增益未闭合，工程师确认后闭合" begin
    r = MilkBalance.run_scenario("S1"; outdir=TMP, dbpath=joinpath(TMP, "s1.duckdb"))
    rep = r.report
    @test ("range_switch" in flags_of(rep)) && ("gain_unconfirmed" in flags_of(rep))
    sep = rep.nodes[findfirst(n -> n.node_id == "sep", rep.nodes)]
    @test sep.status_mass === MilkBalance.open        # +8% 量程2增益 -> 分离器质量未闭合
    @test sep.status_fat === MilkBalance.open
    # 工程师确认量程2增益 +0.08
    r2 = MilkBalance.run_scenario("S1"; outdir=TMP, dbpath=joinpath(TMP, "s1b.duckdb"),
                                  gain_correction=0.08)
    rep2 = r2.report
    @test !("gain_unconfirmed" in flags_of(rep2))
    @test "range_switch" in flags_of(rep2)
    for n in rep2.nodes
        @test n.status_mass === MilkBalance.closed
        @test n.status_fat === MilkBalance.closed
        @test n.status_solids === MilkBalance.closed
    end
    @test rep2.total.status_mass === MilkBalance.closed
end

@testset "S2 脱脂乳样晚到：组成不全而不是误判闭合/未闭合" begin
    r = MilkBalance.run_scenario("S2"; outdir=TMP, dbpath=joinpath(TMP, "s2.duckdb"))
    rep = r.report
    f = flags_of(rep)
    @test "sample_late" in f && "missing_stream_composition" in f
    @test "skim" in rep.missing_streams
    sep = rep.nodes[findfirst(n -> n.node_id == "sep", rep.nodes)]
    blend = rep.nodes[findfirst(n -> n.node_id == "blend", rep.nodes)]
    @test sep.status_mass === MilkBalance.closed
    @test sep.status_fat === MilkBalance.inconclusive && sep.status_solids === MilkBalance.inconclusive
    @test blend.status_fat === MilkBalance.inconclusive
    @test "skim" in sep.missing_composition
    # 全厂脂肪仍可由原奶/产品/奶油/回流判定闭合
    @test rep.total.status_fat === MilkBalance.closed
    # 模拟样品晚到后补录：工程师接受时延并拿到结果 -> 组成闭合
    sc = scenario("S2")
    samples = [MilkBalance.LabSample(
        s.id == "skim_1200" ? "skim_3000" : s.id, s.stream_id,
        s.stream_id == "skim" ? 3000.0 : s.taken_at,
        s.stream_id == "skim" ? 3500.0 : s.received_at,
        s.fat, s.solids, s.basis, true) for s in sc.samples]
    delay = copy(sc.engineer.sample_delay_ok); delay["skim"] = true
    eng = MilkBalance.EngineerInputs(true, delay, sc.engineer.holdups, sc.engineer.range_gains)
    sc2 = Scenario(sc.id, sc.title, sc.spec, sc.nodes, sc.streams, sc.meters,
                   sc.mirror, samples, eng, sc.reflux_kg, sc.reflux_cross, sc.expect_flags)
    rep2 = MilkBalance.reconcile(sc2)
    sep2 = rep2.nodes[findfirst(n -> n.node_id == "sep", rep2.nodes)]
    @test sep2.status_fat === MilkBalance.closed
    @test isempty(rep2.missing_streams)
end

@testset "S3 回流跨批：标记且按外部输入落在共同边界内" begin
    r = MilkBalance.run_scenario("S3"; outdir=TMP, dbpath=joinpath(TMP, "s3.duckdb"))
    rep = r.report
    @test "reflux_cross_batch" in flags_of(rep)
    reflux = r.scenario.streams[findfirst(s -> s.id == "reflux", r.scenario.streams)]
    @test reflux.crosses_batch && reflux.external_in
    rb = rep.branches[findfirst(b -> b.stream_id == "reflux", rep.branches)]
    @test rb.mass.x ≈ 180 atol=3
    @test rep.total.status_mass === MilkBalance.closed
end

@testset "S4 罐底旧料未登记：质量残差浮现 ~70/190 kg" begin
    r = MilkBalance.run_scenario("S4"; outdir=TMP, dbpath=joinpath(TMP, "s4.duckdb"))
    rep = r.report
    @test "unregistered_holdup" in flags_of(rep)
    blend = rep.nodes[findfirst(n -> n.node_id == "blend", rep.nodes)]
    @test blend.status_mass === MilkBalance.open
    # 回配罐：进-出 = -70 kg（旧料未计为输入）
    @test blend.residual_mass.x ≈ -70 atol=6
    # 全厂：缺少未登记的 190 kg 持液减少
    @test rep.total.residual_mass.x ≈ -190 atol=8
    # 登记补录后（含旧料，370→180）应闭合
    sc = scenario("S4")
    using MilkBalance: TankHoldup
    hol = [sc.engineer.holdups[1],
           TankHoldup("buf", 370.0, 180.0, true, 370*0.03524, 180*0.03524,
                      370*0.1215, 180*0.1215)]
    eng = MilkBalance.EngineerInputs(true, sc.engineer.sample_delay_ok, hol,
                                     sc.engineer.range_gains)
    sc2 = Scenario(sc.id, sc.title, sc.spec, sc.nodes, sc.streams, sc.meters,
                   sc.mirror, sc.samples, eng, sc.reflux_kg, sc.reflux_cross, sc.expect_flags)
    rep2 = MilkBalance.reconcile(sc2)
    @test rep2.total.status_mass === MilkBalance.closed
    @test !("unregistered_holdup" in flags_of(rep2))
end

@testset "S5 干湿基混淆：标记且分离器脂肪显著未闭合" begin
    r = MilkBalance.run_scenario("S5"; outdir=TMP, dbpath=joinpath(TMP, "s5.duckdb"))
    rep = r.report
    @test "basis_mixup" in flags_of(rep)
    sep = rep.nodes[findfirst(n -> n.node_id == "sep", rep.nodes)]
    @test sep.status_fat === MilkBalance.open
    @test abs(sep.residual_fat.x) > 50    # 约 -91 kg
    # 误录标记不静默改写：脱脂乳脂肪质量按录入值计算
    sk = rep.branches[findfirst(b -> b.stream_id == "skim", rep.branches)]
    @test sk.fat.x ≈ 0.0112 * TRUE_FLOW["skim"] atol=5
end

@testset "Arrow 镜像往返 + DuckDB 注册视图" begin
    sc = scenario("S3")
    paths = MilkBalance.persist_mirror(sc, TMP)
    df = MilkBalance.read_arrow(paths["raw"])
    @test df isa DataFrame
    @test size(df, 1) == 361
    @test names(df) == ["t","stream_id","flow_kg_h","density_kg_m3","range_idx","quality"]
    @test all(df.stream_id .== "raw")
    db = MilkBalance.open_db(joinpath(TMP, "arrow_view.duckdb"))
    res = MilkBalance.register_arrow(db, paths["cream"], "v_cream")
    n = DataFrame(MilkBalance.DuckDB.DBInterface.execute(db,
        "SELECT count(*) AS n, avg(flow_kg_h) AS q FROM v_cream WHERE quality='good'"))
    @test n.n[1] > 300
    MilkBalance.DuckDB.DBInterface.close!(db)
    # 样品 Arrow 往返
    sdf = MilkBalance.read_arrow(joinpath(TMP, "arrow", sc.spec.batch_id, "samples.arrow"))
    @test size(sdf, 1) == 6
end

@testset "DuckDB 持久化：拓扑/窗口/样品索引/结果可查" begin
    path = joinpath(TMP, "persist.duckdb")
    r = MilkBalance.run_scenario("S2"; outdir=TMP, dbpath=path)
    db = MilkBalance.open_db(path)
    @test DataFrame(MilkBalance.DuckDB.DBInterface.execute(db,
        "SELECT count(*) n FROM streams"))[!,:n][1] == 6
    @test DataFrame(MilkBalance.DuckDB.DBInterface.execute(db,
        "SELECT count(*) n FROM nodes"))[!,:n][1] == 6
    w = DataFrame(MilkBalance.DuckDB.DBInterface.execute(db, "SELECT * FROM windows"))
    @test w.batch_id[1] == "B-S2"
    smp = DataFrame(MilkBalance.DuckDB.DBInterface.execute(db,
        "SELECT basis FROM samples WHERE stream_id='skim'"))
    @test size(smp, 1) == 1
    cl = DataFrame(MilkBalance.DuckDB.DBInterface.execute(db,
        "SELECT status_fat FROM closures WHERE node_id='sep'"))
    @test cl.status_fat[1] == "inconclusive"
    fl = DataFrame(MilkBalance.DuckDB.DBInterface.execute(db, "SELECT flag FROM flags"))
    @test any(startswith("sample_late"), fl.flag)
    MilkBalance.DuckDB.DBInterface.close!(db)
end

@testset "工程师未确认稳定段 -> unstable 标记，组成区间仍可给出但提示" begin
    sc = scenario("S3")
    eng = MilkBalance.EngineerInputs(false, sc.engineer.sample_delay_ok,
                                     sc.engineer.holdups, sc.engineer.range_gains)
    sc2 = Scenario(sc.id, sc.title, sc.spec, sc.nodes, sc.streams, sc.meters,
                   sc.mirror, sc.samples, eng, sc.reflux_kg, sc.reflux_cross, sc.expect_flags)
    rep = MilkBalance.reconcile(sc2)
    @test !rep.stable
    @test "unstable_window" in flags_of(rep)
end

@testset "Plotly HTML 生成（无头可运行）" begin
    r = MilkBalance.run_scenario("S2"; outdir=TMP, dbpath=joinpath(TMP, "plot.duckdb"))
    p = joinpath(TMP, "p.html")
    MilkBalance.write_plot_html(p, r.report; title="测试图")
    html = read(p, String)
    @test occursin("plotly", html)
    @test occursin("各支路", html)
    @test occursin("null", html)   # 缺组成的残差点为 null
end

@testset "边界声明：不输出标准化比例建议" begin
    r = MilkBalance.run_scenario("S1"; outdir=TMP, dbpath=joinpath(TMP, "nostd.duckdb"))
    @test !occursin("推荐比例", r.text)
    @test occursin("不推荐标准化", r.text)
end

# ---------------- 在线脂肪仪偏差复核 ----------------

review_flags_of(rev) = Set(split(f, ':')[1] for f in rev.flags)

@testset "时延匹配：实验室样对应分析仪历史时刻" begin
    w = MilkBalance.WindowSpec(0.0, 3600.0, 300.0, 3300.0, "B-T")
    spec = MilkBalance.AnalyzerSpec("product", 0.08, 120.0, 60.0, 0.001)
    # 分析仪读数在 t=1000 处阶跃：前 0.030 后 0.040
    rdgs = [MilkBalance.AnalyzerReading(Float64(t), "product",
                                        t < 1000 ? 0.030 : 0.040, 20.0,
                                        MilkBalance.q_good, 1) for t in 0:10:3600]
    s1 = MilkBalance.LabSample("product_1050", "product", 1050.0, 2000.0,
                               0.040, 0.1215, MilkBalance.wet, true)
    p1 = MilkBalance.match_sample_to_analyzer(s1, spec, rdgs,
                                              Tuple{Float64,Float64}[], Float64[], w)
    @test p1.analyzer_t == 930.0            # 1050 - 120 s 样品时延
    @test p1.online_fat ≈ 0.030             # 匹配到阶跃前的读数，证明时延生效
    @test p1.deviation ≈ -0.010
    @test p1.used
    s2 = MilkBalance.LabSample("product_1200", "product", 1200.0, 2000.0,
                               0.040, 0.1215, MilkBalance.wet, true)
    p2 = MilkBalance.match_sample_to_analyzer(s2, spec, rdgs,
                                              Tuple{Float64,Float64}[], Float64[], w)
    @test p2.online_fat ≈ 0.040
    @test p2.deviation ≈ 0.0 atol=1e-12
end

@testset "冻结段自检：未打 q_stale 标记的恒值保持也能识别" begin
    rdgs = [MilkBalance.AnalyzerReading(Float64(t), "product",
                                        200 <= t <= 300 ? 0.0357 :
                                            0.03524 + 0.0001 * sin(t),
                                        20.0, MilkBalance.q_good, 1) for t in 0:10:3600]
    ranges = MilkBalance.detect_stale_runs(rdgs)
    @test any(r -> r[1] <= 250 <= r[2], ranges)
    # 正常噪声段不误判
    @test !any(r -> r[1] <= 1500 <= r[2] && r[2] - r[1] > 50, ranges)
end

@testset "超量程：读数超量程上限即剔除（无质量标记也生效）" begin
    w = MilkBalance.WindowSpec(0.0, 3600.0, 300.0, 3300.0, "B-T")
    spec = MilkBalance.AnalyzerSpec("product", 0.08, 120.0, 60.0, 0.001)
    base = [MilkBalance.AnalyzerReading(Float64(t), "product", 0.0355, 20.0,
                                        MilkBalance.q_good, 1) for t in 0:10:3600]
    # 1680 s 单点冲到 0.12（> 量程 0.08），质量标记仍为 good
    rdgs = [r.t == 1680.0 ?
            MilkBalance.AnalyzerReading(r.t, r.stream_id, 0.12, r.temp_c,
                                        MilkBalance.q_good, 1) : r for r in base]
    s = MilkBalance.LabSample("product_1800", "product", 1800.0, 2700.0,
                              0.03524, 0.1215, MilkBalance.wet, true)
    p = MilkBalance.match_sample_to_analyzer(s, spec, rdgs,
                                             Tuple{Float64,Float64}[], Float64[], w)
    @test p.used
    @test any(startswith("overrange_excluded"), p.reasons)
    @test p.online_fat ≈ 0.0355             # 未被 0.12 拉高
end

@testset "流量段边界检测：量程切换成边界，平稳支路无边界" begin
    sc = scenario("S10")
    b = MilkBalance.flow_segment_boundaries(sc.mirror, "cream")
    @test 780.0 in b
    @test isempty(MilkBalance.flow_segment_boundaries(sc.mirror, "raw"))
end

@testset "S6 实验室样取在非稳态：展示偏差但不计入校准统计" begin
    r = MilkBalance.run_scenario("S6"; outdir=TMP, dbpath=joinpath(TMP, "s6.duckdb"))
    rev = r.review
    @test "analyzer_nonsteady_sample" in review_flags_of(rev)
    sr = rev.streams[1]
    p_non = sr.points[findfirst(p -> p.taken_at == 150.0, sr.points)]
    @test !p_non.used && !isnan(p_non.deviation)     # 非稳态点仍展示偏差
    @test "nonsteady_sample" in p_non.reasons
    p_ok = sr.points[findfirst(p -> p.taken_at == 1800.0, sr.points)]
    @test p_ok.used
    @test sr.n_used == 1
    @test sr.status === MilkBalance.cal_ok
    @test r.report.total.status_mass === MilkBalance.closed   # 物料闭合不受影响
end

@testset "S7 分析仪清洗后保持旧值：冻结窗无法匹配" begin
    r = MilkBalance.run_scenario("S7"; outdir=TMP, dbpath=joinpath(TMP, "s7.duckdb"))
    rev = r.review
    @test "analyzer_stale_hold" in review_flags_of(rev)
    sr = rev.streams[1]
    p = sr.points[findfirst(p -> p.taken_at == 2550.0, sr.points)]
    @test !p.used && isnan(p.deviation)
    @test "stale_hold" in p.reasons
    p_ok = sr.points[findfirst(p -> p.taken_at == 1800.0, sr.points)]
    @test p_ok.used
    @test sr.n_used == 1
    @test sr.status === MilkBalance.cal_ok
end

@testset "S8 单点超量程：剔除单点，窗内其余读数仍参与匹配" begin
    r = MilkBalance.run_scenario("S8"; outdir=TMP, dbpath=joinpath(TMP, "s8.duckdb"))
    rev = r.review
    @test "analyzer_overrange_excluded" in review_flags_of(rev)
    sr = rev.streams[1]
    p = sr.points[findfirst(p -> p.taken_at == 1800.0, sr.points)]
    @test p.used
    @test any(startswith("overrange_excluded"), p.reasons)
    @test p.online_fat ≈ 0.03524 + 0.0005 atol=0.0004   # 未被超量程点拉高
    @test sr.status === MilkBalance.cal_ok
end

@testset "S9 温度补偿版本改变：分组评估，版本间差异触发校准可疑" begin
    r = MilkBalance.run_scenario("S9"; outdir=TMP, dbpath=joinpath(TMP, "s9.duckdb"))
    rev = r.review
    fl = review_flags_of(rev)
    @test "analyzer_tcomp_change" in fl
    @test "analyzer_cal_suspect" in fl
    sr = rev.streams[1]
    @test sr.status === MilkBalance.cal_suspect
    @test sr.tcomp_versions == [1, 2]
    @test sr.version_mean_dev[1] > 0 && sr.version_mean_dev[2] < 0
    @test abs(sr.version_mean_dev[1] - sr.version_mean_dev[2]) > 0.001
    @test r.report.total.status_mass === MilkBalance.closed
end

@testset "S10 一只样对应两个流量段：跨段点剔除出统计" begin
    r = MilkBalance.run_scenario("S10"; outdir=TMP, dbpath=joinpath(TMP, "s10.duckdb"))
    rev = r.review
    @test "analyzer_spans_flow_segments" in review_flags_of(rev)
    sr = rev.streams[1]
    p = sr.points[findfirst(p -> p.taken_at == 900.0, sr.points)]
    @test !p.used
    @test "spans_flow_segments" in p.reasons
    @test p.analyzer_t == 780.0               # 时延回推正好落在量程切换点
    p2 = sr.points[findfirst(p -> p.taken_at == 1500.0, sr.points)]
    @test p2.used
    @test sr.n_used == 1
    @test r.report.total.status_mass === MilkBalance.closed
    @test "range_switch" in flags_of(r.report)
end

@testset "偏差复核不修正在线原始值、不进入物料闭合" begin
    sc = scenario("S8")
    before = deepcopy(sc.analyzer_readings)
    rev = MilkBalance.review_analyzers(sc)
    @test all(sc.analyzer_readings .== before)          # 在线读数未被改写
    rep = MilkBalance.reconcile(sc)
    @test rep.total.status_mass === MilkBalance.closed
    @test !any(startswith(f, "analyzer_") for f in rep.flags)   # 闭合标记不受复核影响
    @test any(startswith(f, "analyzer_") for f in rev.flags)
    r = MilkBalance.run_scenario("S8"; outdir=TMP, dbpath=joinpath(TMP, "s8b.duckdb"))
    @test occursin("在线脂肪仪偏差复核", r.text)
    @test occursin("不自动修正", r.text)
    # 无分析仪的情景不出现复核段
    r1 = MilkBalance.run_scenario("S1"; outdir=TMP, dbpath=joinpath(TMP, "s1c.duckdb"))
    @test !occursin("在线脂肪仪偏差复核", r1.text)
end

@testset "复核结果 DuckDB 持久化与 Arrow 往返" begin
    path = joinpath(TMP, "review.duckdb")
    r = MilkBalance.run_scenario("S8"; outdir=TMP, dbpath=path)
    db = MilkBalance.open_db(path)
    st = DataFrame(MilkBalance.DuckDB.DBInterface.execute(db,
        "SELECT status, n_used FROM analyzer_status WHERE batch_id='B-S8'"))
    @test st.status[1] == "cal_ok"
    @test st.n_used[1] == 1
    pt = DataFrame(MilkBalance.DuckDB.DBInterface.execute(db,
        "SELECT used, reasons FROM analyzer_points WHERE batch_id='B-S8'"))
    @test size(pt, 1) == 1
    @test pt.used[1] == true
    @test occursin("overrange_excluded", pt.reasons[1])
    idx = DataFrame(MilkBalance.DuckDB.DBInterface.execute(db,
        "SELECT stream_id, arrow_path, n_rows FROM analyzer_index WHERE batch_id='B-S8'"))
    @test idx.stream_id[1] == "product"
    back = MilkBalance.frame_to_analyzer(MilkBalance.read_arrow(idx.arrow_path[1]))
    @test length(back) == 361
    @test count(x -> x.quality == MilkBalance.q_overrange, back) == 1
    MilkBalance.DuckDB.DBInterface.close!(db)
end

@testset "复核偏差趋势图写入 HTML（无头可运行）" begin
    r = MilkBalance.run_scenario("S6"; outdir=TMP, dbpath=joinpath(TMP, "s6p.duckdb"))
    html = read(r.html, String)
    @test occursin("偏差趋势", html)
    @test occursin("analyzer", html)
end

@testset "S6..S10 期望复核标记自检" begin
    for id in ("S6", "S7", "S8", "S9", "S10")
        r = MilkBalance.run_scenario(id; outdir=TMP,
                                     dbpath=joinpath(TMP, "exp_$id.duckdb"))
        ok, miss, _ = MilkBalance.expect_review_flags_present(
            r.review, r.scenario.expect_review_flags)
        @test ok
        okb, _, _ = MilkBalance.expect_flags_present(r.report, r.scenario.expect_flags)
        @test okb
    end
end
