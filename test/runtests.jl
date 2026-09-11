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
