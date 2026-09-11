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
end

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
    error("未知情景 $id（可选 S1..S5）")
end
all_scenarios() = [scenario_cream_switch(), scenario_skim_late(), scenario_reflux_cross(),
                   scenario_old_bottom(), scenario_basis_mixup()]
