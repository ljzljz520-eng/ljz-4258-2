# 测试情景与真值数据生成。
#
# 共同窗口 t0=0..t1=3600 s，稳定段 300..3300 s。
# 真值流量(kg/h)（基线严格闭合）：
#   原奶 10000 → 分离机 → 稀奶油总 1042.78（其中 902.78 回配、140 出品）+ 脱脂乳 8957.22
#   回配罐：902.78 + 8957.22 + 回流120 = 产品 9980
#   回流自缓冲罐，窗口内 120 kg，由缓冲罐持液减少 120 kg 平衡（登记）
# 全厂：原奶 10000 = 产品 9980 + 稀奶油出品 140 + Δ持液(0+(-120) 已计)
# 组成(湿基)：原奶 4.00%F/12.60%S；脱脂 0.10%F/8.90%S；稀奶油 37.5%F/44.38%S；
#             产品/回流 3.524%F/12.15%S。
# 密度(kg/m3)：原奶1030，脱脂1035，稀奶油989，产品1030，回流1030。

const T0 = 0.0
const T1 = 3600.0
const S0 = 300.0
const S1 = 3300.0
const DT = 10.0

const TRUE_FLOW = Dict("raw" => 10000.0, "skim" => 8957.22,
                       "cream" => 902.78, "cream_out" => 140.0,
                       "product" => 9980.0, "reflux" => 120.0)
const TRUE_DENS = Dict("raw" => 1030.0, "skim" => 1035.0,
                       "cream" => 989.0, "cream_out" => 989.0,
                       "product" => 1030.0, "reflux" => 1030.0)
const TRUE_FAT  = Dict("raw" => 0.04000, "skim" => 0.00100,
                       "cream" => 0.37500, "cream_out" => 0.37500,
                       "product" => 0.03524, "reflux" => 0.03524)
const TRUE_SOL  = Dict("raw" => 0.12600, "skim" => 0.08900,
                       "cream" => 0.44380, "cream_out" => 0.44380,
                       "product" => 0.12150, "reflux" => 0.12150)

default_topology() = (
    nodes = [
        Node("raw_tank", "原料奶罐", tank_source),
        Node("sep", "离心分离机", separator),
        Node("blend", "回配罐", blend),
        Node("buf", "缓冲罐", tank_buffer),
        Node("cream_silo", "稀奶油暂存/出品", outlet),
        Node("out", "产品出口", outlet),
    ],
    streams = [
        Stream(; id="raw", name="原奶进料", src="raw_tank", dst="sep",
               external_in=true, external_out=false, is_reflux=false),
        Stream(; id="cream", name="稀奶油回配支路", src="sep", dst="blend",
               external_in=false, external_out=false, is_reflux=false),
        Stream(; id="cream_out", name="稀奶油出品", src="sep", dst="cream_silo",
               external_in=false, external_out=true, is_reflux=false),
        Stream(; id="skim", name="脱脂乳支路", src="sep", dst="blend",
               external_in=false, external_out=false, is_reflux=false),
        Stream(; id="product", name="回配产品", src="blend", dst="out",
               external_in=false, external_out=true, is_reflux=false),
        Stream(; id="reflux", name="回流（缓冲罐→回配罐）", src="buf", dst="blend",
               external_in=false, external_out=false, is_reflux=true),
    ],
)

default_meters() = [
    MeterSpec("raw",       [(0.0, 6000.0), (6000.0, 15000.0)], 0.0030, 0.0),
    MeterSpec("skim",      [(0.0, 6000.0), (6000.0, 15000.0)], 0.0030, 0.0),
    MeterSpec("cream",     [(0.0, 500.0),  (500.0, 2000.0)],   0.0050, 0.0),
    MeterSpec("cream_out", [(0.0, 1000.0)],                     0.0050, 0.0),
    MeterSpec("product",   [(0.0, 6000.0), (6000.0, 15000.0)], 0.0030, 0.0),
    MeterSpec("reflux",    [(0.0, 1000.0)],                     0.0060, 0.0),
]

# 组成扩展不确定度（湿基，绝对，k=2）
const FAT_U = Dict("raw" => 0.00060, "skim" => 0.00030, "cream" => 0.00250,
                   "cream_out" => 0.00250, "product" => 0.00060, "reflux" => 0.00060)
const SOL_U = Dict("raw" => 0.00090, "skim" => 0.00090, "cream" => 0.00300,
                   "cream_out" => 0.00300, "product" => 0.00090, "reflux" => 0.00090)

# 湿基脂肪物理合理上限（用于干湿基混淆的合理性核查）
const PLAUS_FAT_MAX = Dict("raw" => 0.09, "skim" => 0.006, "cream" => 0.60,
                           "cream_out" => 0.60, "product" => 0.08, "reflux" => 0.08)

# 未确认量程切换增益：附加 2% 仪表系统不确定度（增益本身须由工程师确认）
const UNCONFIRMED_GAIN_U = 0.02

_pn(seed::String, i::Int) = (h = hash(seed * "#" * string(i)); (Int(h >> 8) % 10000) / 10000.0 - 0.5)

default_meters_dict() = Dict(m.stream_id => m for m in default_meters())

function range_index(md::Dict{String,MeterSpec}, sid::String, q::Real)
    m = md[sid]
    for (i, (lo_, hi_)) in enumerate(m.ranges)
        q >= lo_ && q <= hi_ && return i
    end
    return length(m.ranges)
end

"""生成支路窗口镜像。
range_switch=(ts, dur, gain2)：ts 前为量程1，其后为量程2；切换后持续 dur 秒打
q_range_switch；gain2 为量程2上未修正的增益偏差（仅施加于量程2样本）。"""
function gen_mirror(stream_id::String; flow_scale::Real=1.0,
                    range_switch::Union{Nothing,Tuple}=nothing,
                    seed::String=stream_id, flow_noise::Real=0.004,
                    skip_stream::Bool=false)
    samples = FlowMirrorSample[]
    gain2 = range_switch === nothing ? 0.0 : range_switch[3]
    for (i, t) in enumerate(T0:DT:T1)
        skip_stream && continue
        qtrue = TRUE_FLOW[stream_id] * flow_scale *
                (1.0 + flow_noise * 2 * _pn(seed, i))
        rng = range_index(default_meters_dict(), stream_id, qtrue)
        qual = q_good
        g = 0.0
        if range_switch !== nothing
            ts, dur, _ = range_switch
            rng = t < ts ? 1 : 2
            if t >= ts && t < ts + dur
                qual = q_range_switch
            end
            if rng == 2
                g = gain2
            end
        end
        q = qtrue * (1.0 + g)
        d = TRUE_DENS[stream_id] + 2.0 * 2 * _pn(seed * "_d", i)
        push!(samples, FlowMirrorSample(t, stream_id, q, d, rng, qual))
    end
    return samples
end

lab_sample(sid, taken, received; fat=TRUE_FAT[sid], solids=TRUE_SOL[sid],
           basis=wet, delay_ok=true) =
    LabSample(sid * "_" * string(Int(taken)), sid, Float64(taken), Float64(received),
              fat, solids, basis, delay_ok)

default_samples() = [
    lab_sample("raw", 900, 1800),
    lab_sample("skim", 1200, 2100),
    lab_sample("cream", 1500, 2400),
    lab_sample("cream_out", 1600, 2500),
    lab_sample("product", 1800, 2700),
    lab_sample("reflux", 2000, 2800),
]

# 基线罐持液：回配罐不变；缓冲罐窗口内减少 120 kg（=回流量，登记）
default_holdups(; registered=true, buf_start=300.0, buf_end=180.0) = [
    TankHoldup("blend", 300.0, 300.0, true, 10.572, 10.572, 36.45, 36.45),
    TankHoldup("buf", buf_start, buf_end, registered,
               buf_start * 0.03524, buf_end * 0.03524,
               buf_start * 0.1215, buf_end * 0.1215),
]

default_window(batch="B-base") = WindowSpec(T0, T1, S0, S1, batch)

default_engineer(; gains=Dict{Tuple{String,Int},Float64}(),
                 holdups=default_holdups(),
                 delay=Dict("raw" => true, "skim" => true, "cream" => true,
                            "cream_out" => true, "product" => true, "reflux" => true)) =
    EngineerInputs(true, delay, holdups, gains)

@kwdef struct Scenario
    id::String
    title::String
    spec::WindowSpec
    nodes::Vector{Node}
    streams::Vector{Stream}
    meters::Vector{MeterSpec}
    mirror::Vector{FlowMirrorSample}
    samples::Vector{LabSample}
    engineer::EngineerInputs
    reflux_kg::Float64 = 0.0
    reflux_cross::Bool = false
    expect_flags::Vector{String} = String[]
    analyzer_readings::Vector{AnalyzerReading} = AnalyzerReading[]
    analyzer_specs::Vector{AnalyzerSpec} = AnalyzerSpec[]
    expect_review_flags::Vector{String} = String[]
end

# 兼容 12 参数位置构造（不含在线分析仪扩展字段）
Scenario(id, title, spec, nodes, streams, meters, mirror, samples, engineer,
         reflux_kg, reflux_cross, expect_flags) =
    Scenario(; id, title, spec, nodes, streams, meters, mirror, samples, engineer,
             reflux_kg, reflux_cross, expect_flags)

_all_mirror(; reflux_scale=1.0, product_scale=1.0, cream_switch=nothing, seed_extra="") =
    vcat(gen_mirror("raw"; seed="raw" * seed_extra),
         gen_mirror("skim"; seed="skim" * seed_extra),
         gen_mirror("cream"; range_switch=cream_switch, seed="cream" * seed_extra),
         gen_mirror("cream_out"; seed="cout" * seed_extra),
         gen_mirror("product"; flow_scale=product_scale, seed="prod" * seed_extra),
         gen_mirror("reflux"; flow_scale=reflux_scale, seed="reflux" * seed_extra))

"""情景1：奶油流量计 780 s 由量程1切到量程2，量程2 未修正增益 +8%；
切换瞬态(30 s)样本剔除；工程师未确认增益时分离器节点质量/脂肪均应未闭合。"""
function scenario_cream_switch()
    topo = default_topology()
    mirror = _all_mirror(; cream_switch=(780.0, 30.0, 0.08), seed_extra="_s1")
    eng = default_engineer()   # gains 为空 = 工程师尚未确认
    Scenario(; id="S1", title="奶油量程切换：量程2未确认增益 +8%，切换瞬态剔除",
             spec=default_window("B-S1"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=default_samples(),
             engineer=eng, reflux_kg=120.0,
             expect_flags=["range_switch", "gain_unconfirmed"])
end

"""情景2：脱脂乳样品晚到（结果 4000 s 才到，超过窗口 3600 s），工程师不接受时延。"""
function scenario_skim_late()
    topo = default_topology()
    mirror = _all_mirror(; seed_extra="_s2")
    samples = LabSample[
        lab_sample("raw", 900, 1800),
        lab_sample("skim", 1200, 4000; delay_ok=false),
        lab_sample("cream", 1500, 2400),
        lab_sample("cream_out", 1600, 2500),
        lab_sample("product", 1800, 2700),
        lab_sample("reflux", 2000, 2800),
    ]
    delay = Dict("raw" => true, "skim" => false, "cream" => true,
                 "cream_out" => true, "product" => true, "reflux" => true)
    eng = default_engineer(; delay=delay)
    Scenario(; id="S2", title="脱脂乳样晚到：窗口关闭时结果未到，时延不被接受",
             spec=default_window("B-S2"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=samples,
             engineer=eng, reflux_kg=120.0,
             expect_flags=["sample_late", "missing_stream_composition"])
end

"""情景3：回流跨批：窗口内 150 kg（180 kg/h）回流来自上一批 B-S3p，
按外部输入纳入共同边界；缓冲罐持液窗口内不变。"""
function scenario_reflux_cross()
    topo = default_topology()
    mirror = _all_mirror(; reflux_scale=180.0 / 120.0,
                         product_scale=10030.0 / 9980.0, seed_extra="_s3")
    streams = map(topo.streams) do s
        s.id == "reflux" ?
            Stream(; id="reflux", name=s.name, src=s.src, dst=s.dst,
                   external_in=true, external_out=false, is_reflux=true,
                   crosses_batch=true) : s
    end
    eng = default_engineer(; holdups=default_holdups(; buf_start=300.0, buf_end=300.0))
    Scenario(; id="S3", title="回流跨批：150 kg 来自上一批，按外部输入纳入边界",
             spec=default_window("B-S3"), nodes=topo.nodes, streams=streams,
             meters=default_meters(), mirror=mirror, samples=default_samples(),
             engineer=eng, reflux_kg=150.0, reflux_cross=true,
             expect_flags=["reflux_cross_batch"])
end

"""情景4：罐底旧料未登记：缓冲罐底另有 70 kg（脂肪约2.47/干物质8.50）未入账，
窗口内随回流进入产品；账面只记 120 kg 持液变化，实际为 190 kg。"""
function scenario_old_bottom()
    topo = default_topology()
    # 产品计量含旧料：9980 + 70 = 10050 kg/h；产品流量噪声减半以便旧料信号清晰
    mirror = vcat(
        gen_mirror("raw"; seed="raw_s4"),
        gen_mirror("skim"; seed="skim_s4"),
        gen_mirror("cream"; seed="cream_s4"),
        gen_mirror("cream_out"; seed="cout_s4"),
        gen_mirror("product"; flow_scale=10050.0 / 9980.0, flow_noise=0.001, seed="prod_s4"),
        gen_mirror("reflux"; seed="reflux_s4"))
    # 工程师账面：300→180（-120），且未登记（核算时该罐持液被排除）
    eng = default_engineer(; holdups=default_holdups(; registered=false))
    Scenario(; id="S4", title="罐底旧料未登记：缓冲罐 70 kg 未入账",
             spec=default_window("B-S4"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=default_samples(),
             engineer=eng, reflux_kg=120.0,
             expect_flags=["unregistered_holdup"])
end

"""情景5：干湿基混淆：脱脂乳脂肪真值 0.10%(湿基)=1.12%(干基)，
录入员把干基数值 1.12% 误当湿基录入（basis=wet, fat=0.0112）。"""
function scenario_basis_mixup()
    topo = default_topology()
    mirror = _all_mirror(; seed_extra="_s5")
    samples = LabSample[
        lab_sample("raw", 900, 1800),
        lab_sample("skim", 1200, 2100; fat=0.0112, basis=wet),   # 误录：干基值当湿基
        lab_sample("cream", 1500, 2400),
        lab_sample("cream_out", 1600, 2500),
        lab_sample("product", 1800, 2700),
        lab_sample("reflux", 2000, 2800),
    ]
    eng = default_engineer()
    Scenario(; id="S5", title="干湿基混淆：脱脂乳干基脂肪 1.12% 被误当湿基录入",
             spec=default_window("B-S5"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=samples,
             engineer=eng, reflux_kg=120.0,
             expect_flags=["basis_mixup"])
end

function scenario(id::AbstractString)
    id == "S1" && return scenario_cream_switch()
    id == "S2" && return scenario_skim_late()
    id == "S3" && return scenario_reflux_cross()
    id == "S4" && return scenario_old_bottom()
    id == "S5" && return scenario_basis_mixup()
    id == "S6" && return scenario_analyzer_nonsteady()
    id == "S7" && return scenario_analyzer_stale()
    id == "S8" && return scenario_analyzer_overrange()
    id == "S9" && return scenario_analyzer_tcomp()
    id == "S10" && return scenario_analyzer_two_segments()
    error("未知情景 $id（可选 S1..S10）")
end
all_scenarios() = [scenario_cream_switch(), scenario_skim_late(), scenario_reflux_cross(),
                   scenario_old_bottom(), scenario_basis_mixup(),
                   scenario_analyzer_nonsteady(), scenario_analyzer_stale(),
                   scenario_analyzer_overrange(), scenario_analyzer_tcomp(),
                   scenario_analyzer_two_segments()]

# ---------------- 在线脂肪仪偏差复核情景（S6..S10） ----------------
# 复核只比对“在线值 vs 同期实验室值”，不修正在线原始值、不进入物料闭合；
# 因此下列情景的物料/脂肪平衡均为基线严格闭合，差异全部在分析仪侧。

const ANALYZER_DT = 10.0

"""生成在线脂肪仪镜像（湿基脂肪分数）。
- bias：固定系统偏差；noise：随机噪声幅度；
- stale_ranges：[(t0,t1,hold)] 清洗后保持旧值区间，读数冻结为 hold 并打 q_stale；
- overrange_at：超量程时刻表，读数冲至 range_max 之上并打 q_overrange；
- tcomp_switch=(ts, extra_bias)：ts 起温度补偿版本 1→2，并叠加额外偏差。"""
function gen_analyzer(stream_id::String; bias::Real=0.0, noise::Real=0.0002,
                      seed::String=stream_id * "_an",
                      stale_ranges::Vector{Tuple{Float64,Float64,Float64}}=Tuple{Float64,Float64,Float64}[],
                      overrange_at::Vector{Float64}=Float64[],
                      overrange_to::Real=0.12,
                      tcomp_switch::Union{Nothing,Tuple{Float64,Float64}}=nothing)
    out = AnalyzerReading[]
    for (i, t) in enumerate(T0:ANALYZER_DT:T1)
        ver = 1
        b = bias
        if tcomp_switch !== nothing && t >= tcomp_switch[1]
            ver = 2
            b += tcomp_switch[2]
        end
        v = TRUE_FAT[stream_id] + b + noise * 2 * _pn(seed, i)
        q = q_good
        for (a, bb, hold) in stale_ranges
            if a <= t <= bb
                v = hold
                q = q_stale
            end
        end
        if t in overrange_at
            v = overrange_to
            q = q_overrange
        end
        temp = 20.0 + 2.0 * 2 * _pn(seed * "_t", i)
        push!(out, AnalyzerReading(t, stream_id, v, temp, q, ver))
    end
    return out
end

product_analyzer_spec(; tol=0.0010) =
    AnalyzerSpec("product", 0.08, 120.0, 60.0, tol)

"""情景6：实验室样取在非稳态——产品样 150 s（稳定段 300 s 之前）取样，
时延匹配仍给出偏差展示，但该点不计入趋势/校准统计。"""
function scenario_analyzer_nonsteady()
    topo = default_topology()
    mirror = _all_mirror(; seed_extra="_s6")
    samples = [default_samples(); lab_sample("product", 150, 900)]
    Scenario(; id="S6", title="在线脂肪仪复核：实验室样取在非稳态（展示但不计入校准统计）",
             spec=default_window("B-S6"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=samples,
             engineer=default_engineer(), reflux_kg=120.0,
             analyzer_readings=gen_analyzer("product"; bias=0.0005, seed="prod_s6"),
             analyzer_specs=[product_analyzer_spec()],
             expect_review_flags=["analyzer_nonsteady_sample"])
end

"""情景7：分析仪清洗后保持旧值——2380..2620 s 读数冻结（q_stale），
2550 s 实验室样的匹配窗全部落在冻结段，该点无法匹配，不计入统计。"""
function scenario_analyzer_stale()
    topo = default_topology()
    mirror = _all_mirror(; seed_extra="_s7")
    samples = [default_samples(); lab_sample("product", 2550, 3000)]
    rdgs = gen_analyzer("product"; bias=0.0005, seed="prod_s7",
                        stale_ranges=[(2360.0, 2620.0, 0.03570)])
    Scenario(; id="S7", title="在线脂肪仪复核：清洗后保持旧值，匹配窗全冻结则该点剔除",
             spec=default_window("B-S7"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=samples,
             engineer=default_engineer(), reflux_kg=120.0,
             analyzer_readings=rdgs, analyzer_specs=[product_analyzer_spec()],
             expect_review_flags=["analyzer_stale_hold"])
end

"""情景8：单点超量程——1700 s 一点读数冲出量程（0.12 > 0.08），
该点剔除后用窗内其余有效读数求均值，匹配点仍计入统计。"""
function scenario_analyzer_overrange()
    topo = default_topology()
    mirror = _all_mirror(; seed_extra="_s8")
    rdgs = gen_analyzer("product"; bias=0.0005, seed="prod_s8",
                        overrange_at=[1700.0])
    Scenario(; id="S8", title="在线脂肪仪复核：单点超量程剔除，窗内其余读数仍可用",
             spec=default_window("B-S8"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=default_samples(),
             engineer=default_engineer(), reflux_kg=120.0,
             analyzer_readings=rdgs, analyzer_specs=[product_analyzer_spec()],
             expect_review_flags=["analyzer_overrange_excluded"])
end

"""情景9：样品温度补偿版本改变——2000 s 起 v1→v2 且叠加 -0.0015 偏差，
按版本分组统计偏差，版本间差异超允差则校准状态可疑。"""
function scenario_analyzer_tcomp()
    topo = default_topology()
    mirror = _all_mirror(; seed_extra="_s9")
    samples = LabSample[
        lab_sample("raw", 900, 1800),
        lab_sample("skim", 1200, 2100),
        lab_sample("cream", 1500, 2400),
        lab_sample("cream_out", 1600, 2500),
        lab_sample("product", 1500, 2400),
        lab_sample("product", 2500, 3200),
        lab_sample("reflux", 2000, 2800),
    ]
    rdgs = gen_analyzer("product"; bias=0.0008, seed="prod_s9",
                        tcomp_switch=(2000.0, -0.0015))
    Scenario(; id="S9", title="在线脂肪仪复核：温度补偿版本切换，分组偏差超允差",
             spec=default_window("B-S9"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=samples,
             engineer=default_engineer(), reflux_kg=120.0,
             analyzer_readings=rdgs, analyzer_specs=[product_analyzer_spec()],
             expect_review_flags=["analyzer_tcomp_change", "analyzer_cal_suspect"])
end

"""情景10：一只样对应两个流量段——奶油支路 780 s 量程切换（增益 0 且工程师已确认），
900 s 取的奶油样经时延回推正好跨流量段边界，该点不计入校准统计。"""
function scenario_analyzer_two_segments()
    topo = default_topology()
    mirror = _all_mirror(; cream_switch=(780.0, 30.0, 0.0), seed_extra="_s10")
    samples = LabSample[
        lab_sample("raw", 900, 1800),
        lab_sample("skim", 1200, 2100),
        lab_sample("cream", 900, 1800),    # 时延 120 s -> 对应分析仪 780 s，跨流量段
        lab_sample("cream", 1500, 2400),
        lab_sample("cream_out", 1600, 2500),
        lab_sample("product", 1800, 2700),
        lab_sample("reflux", 2000, 2800),
    ]
    eng = default_engineer(; gains=Dict{Tuple{String,Int},Float64}(("cream", 2) => 0.0))
    cream_spec = AnalyzerSpec("cream", 0.60, 120.0, 60.0, 0.0040)
    Scenario(; id="S10", title="在线脂肪仪复核：一只样对应两个流量段，该点剔除出统计",
             spec=default_window("B-S10"), nodes=topo.nodes, streams=topo.streams,
             meters=default_meters(), mirror=mirror, samples=samples,
             engineer=eng, reflux_kg=120.0,
             analyzer_readings=gen_analyzer("cream"; bias=0.0020, noise=0.0008,
                                            seed="cream_s10"),
             analyzer_specs=[cream_spec],
             expect_flags=["range_switch"],
             expect_review_flags=["analyzer_spans_flow_segments"])
end
