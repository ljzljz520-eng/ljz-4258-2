# 数据模型：乳脂回配核算应用
# 所有质量单位 kg，组分（脂肪/干物质）质量 kg，组成以湿基质量分数给出（0..1）。

"""节点类型：原料罐、离心机（分离机）、回配罐、产品口。"""
@enum NodeKind tank_source separator blend tank_buffer outlet

"""计量数据质量标记。"""
@enum Quality q_good q_range_switch q_stale q_missing

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
