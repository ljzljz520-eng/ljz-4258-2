# 数据模型：乳脂回配核算应用
# 所有质量单位 kg，组分（脂肪/干物质）质量 kg，组成以湿基质量分数给出（0..1）。

"""节点类型：原料罐、离心机（分离机）、回配罐、产品口。"""
@enum NodeKind tank_source separator blend tank_buffer outlet

"""计量数据质量标记。"""
@enum Quality q_good q_range_switch q_stale q_missing q_overrange

"""脂肪基准：湿基(wet, 脂肪/全样) 或 干基(dry, 脂肪/干物质)。"""
@enum FatBasis wet dry

@kwdef struct IV
    """以均值 ± 扩展不确定度(k=2)表示的区间量。"""
    x::Float64
    u::Float64            # 半宽，>=0
end
IV(x::Real, u::Real) = IV(Float64(x), Float64(u))
lo(z::IV) = z.x - z.u
hi(z::IV) = z.x + z.u
mid(z::IV) = z.x
Base.isempty(z::IV) = z.u < 0

@kwdef struct Node
    id::String
    name::String
    kind::NodeKind
end

@kwdef struct Stream
    """工艺支路。raw 原奶进、cream 稀奶油、skim 脱脂乳、product 产品、reflux 回流。"""
    id::String
    name::String
    src::String
    dst::String
    external_in::Bool
    external_out::Bool
    is_reflux::Bool
    crosses_batch::Bool = false
end

@kwdef struct MeterSpec
    """流量计规格与量程。"""
    stream_id::String
    ranges::Vector{Tuple{Float64,Float64}}   # (量程下限 kg/h, 量程上限 kg/h)
    base_rel::Float64                        # 基线相对扩展不确定度(k=2)
    gain_rel::Float64                        # 额外增益系统偏差（未校准的量程切换残留）
end

@kwdef struct FlowMirrorSample
    """现场流量/密度镜像采样，先落 Apache Arrow。"""
    t::Float64                  # 相对窗口起点的秒
    stream_id::String
    flow_kg_h::Float64          # 瞬时质量流量
    density_kg_m3::Float64
    range_idx::Int
    quality::Quality
end

@kwdef struct LabSample
    """实验室样品索引与组成结果。"""
    id::String
    stream_id::String
    taken_at::Float64           # 实际取样时刻(s)
    received_at::Float64        # 结果到达时刻(s)
    fat::Float64                # 脂肪质量分数
    solids::Float64             # 干物质质量分数
    basis::FatBasis             # wet/dry
    delay_ok::Bool
end

@kwdef struct RangeState
    """量程切换事件登记。"""
    stream_id::String
    t::Float64
    from_range::Int
    to_range::Int
    gain_correction::Union{Float64,Nothing}  # 工程师确认的增益修正，nothing=未确认
end

@kwdef struct TankHoldup
    """罐内持液：窗口起止存量。"""
    tank_id::String
    start_kg::Float64
    end_kg::Float64
    registered::Bool            # 是否登记（罐底旧料未登记 -> false）
    fat_start::Float64
    fat_end::Float64
    solids_start::Float64
    solids_end::Float64
end

@kwdef struct WindowSpec
    """共同边界：稳定段计算窗口，所有支路共用。"""
    t0::Float64
    t1::Float64
    stable0::Float64
    stable1::Float64
    batch_id::String
end

@kwdef struct EngineerInputs
    """工程师确认项：稳定段、样品时延、罐内持液；程序不做标准化比例推荐、不控制分离机。"""
    stable_confirmed::Bool
    sample_delay_ok::Dict{String,Bool}
    holdups::Vector{TankHoldup}
    range_gains::Dict{Tuple{String,Int},Float64}   # (stream, 目标量程) -> 增益修正
end

@kwdef struct BranchMass
    """一支路在共同窗口内的积分质量与组分。"""
    stream_id::String
    mass::IV
    fat::IV
    solids::IV
    coverage::Float64            # 有效（非切换瞬态）积分覆盖比
    switched::Bool
end

@enum ClosureStatus closed open inconclusive

@kwdef struct NodeClosure
    """一个边界节点（或全厂）的干物质/脂肪闭合。"""
    node_id::String
    label::String
    residual_mass::IV
    residual_fat::IV
    residual_solids::IV
    status_mass::ClosureStatus
    status_fat::ClosureStatus
    status_solids::ClosureStatus
    unaccounted_mass::IV
    unaccounted_fat::IV
    unaccounted_solids::IV
    missing_composition::Vector{String}   # 该边界上缺组成样品的支路
end

@kwdef struct WindowReport
    spec::WindowSpec
    branches::Vector{BranchMass}
    nodes::Vector{NodeClosure}
    total::NodeClosure
    flags::Vector{String}
    actual_fat_interval::IV          # 实际产品脂肪组成区间（湿基）
    actual_solids_interval::IV
    missing_streams::Vector{String}  # 未计物流
    compositions_used::Dict{String,LabSample}
    stable::Bool
end

# ---------------- 在线脂肪仪偏差复核 ----------------
# 工程边界：偏差复核只做“在线值 vs 同期实验室值”的比对、趋势与校准状态评估；
# 程序不自动修正、不回写任何在线原始读数，复核结果也不进入物料闭合。

@kwdef struct AnalyzerReading
    """在线脂肪仪镜像采样（先落 Apache Arrow，再供复核读取）。"""
    t::Float64                  # 相对窗口起点的秒
    stream_id::String
    fat_pct::Float64            # 在线脂肪读数（湿基质量分数，原始值，不做任何修正）
    temp_c::Float64             # 样品温度
    quality::Quality            # q_good / q_stale(清洗后保持旧值) / q_overrange / q_missing
    tcomp_version::Int          # 样品温度补偿算法版本
end

@kwdef struct AnalyzerSpec
    """一台在线脂肪仪的计量规格与复核参数（工程师登记）。"""
    stream_id::String
    range_max::Float64          # 仪表认证量程上限（湿基脂肪分数），超出即超量程
    transport_delay::Float64    # 样品时延(s)：分析仪在取样口上游，实验室样对应 t_取样-时延
    match_halfwin::Float64      # 匹配半窗(s)：在对应时刻前后各取该宽度求在线均值
    tol::Float64                # 校准允差（绝对，湿基脂肪分数，k=2 量级）
end

"""校准状态：正常 / 偏差可疑 / 趋势漂移 / 数据不足。"""
@enum CalStatus cal_ok cal_suspect cal_drift cal_insufficient

@kwdef struct DeviationPoint
    """一只实验室样与在线读数的时延匹配结果（仅展示，不回写）。"""
    sample_id::String
    stream_id::String
    taken_at::Float64           # 取样时刻(s)
    analyzer_t::Float64         # 对应分析仪时刻 = taken_at - 样品时延
    online_fat::Float64         # 匹配窗内有效在线均值（无法匹配为 NaN）
    lab_fat::Float64            # 实验室湿基脂肪
    deviation::Float64          # 在线 − 实验室（无法匹配为 NaN）
    used::Bool                  # 是否计入偏差趋势/校准统计
    reasons::Vector{String}     # 排除或提示原因（非稳态/保持旧值/超量程/跨流量段/补偿版本混合）
    tcomp_version::Int          # 匹配所用温度补偿版本（无法匹配为 0）
end

@kwdef struct AnalyzerStreamReview
    """一台分析仪的偏差趋势与校准状态结论。"""
    stream_id::String
    points::Vector{DeviationPoint}
    n_used::Int
    mean_dev::Float64           # 计入点的平均偏差（在线−实验室）
    slope_per_h::Float64        # 偏差趋势斜率（每小时），点数不足为 NaN
    status::CalStatus
    tcomp_versions::Vector{Int} # 计入点出现的温度补偿版本
    version_mean_dev::Dict{Int,Float64}  # 各版本各自的平均偏差
    tol::Float64                # 校准允差（绝对，湿基脂肪分数）
    flags::Vector{String}
end

@kwdef struct AnalyzerReview
    """整批在线脂肪仪偏差复核结果；不进入物料闭合，不修正在线原始值。"""
    batch_id::String
    streams::Vector{AnalyzerStreamReview}
    flags::Vector{String}
end
