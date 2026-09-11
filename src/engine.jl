# 核算引擎：共同边界内积分支路质量与组分，做节点/全厂干物质与脂肪闭合。
# 工程师确认稳定段、样品时延、罐内持液；程序只报告实际组成区间、未计物流、
# 扩展不确定度(k=2)与标记；不推荐标准化比例，不向分离机发任何控制指令。

using Statistics: mean

struct ReconError <: Exception
    msg::String
end

# ---------------- 公共工具 ----------------

getstreams(sc) = sc.streams
find_stream(sc, sid) = sc.streams[findfirst(s -> s.id == sid, sc.streams)]

"该支路在窗口内是否计质量：跨批回流当外部输入（正号）；否则按 src/dst 方向。"
function stream_sign(s::Stream)
    s.external_in && return +1
    s.external_out && return -1
    return 0   # 内部支路
end

"在指定节点处该支路的符号：进入节点 +，离开节点 -。"
function sign_at_node(s::Stream, node_id::AbstractString)
    s.dst == node_id && return +1
    s.src == node_id && return -1
    return 0
end

# ---------------- 积分 ----------------

"""窗口内质量积分（kg）与有效覆盖比；切换瞬态样本剔除并打标记。
若工程师确认了目标量程增益修正，则对受影响样本流量除以（1+gain）。"""
function integrate_mass(sc::Scenario, sid::String)
    w = sc.spec
    rows = filter(x -> x.stream_id == sid && x.t >= w.t0 && x.t <= w.t1, sc.mirror)
    isempty(rows) && return IV(0.0, Inf), 0.0, false, true
    meter = sc.meters[findfirst(m -> m.stream_id == sid, sc.meters)]
    total_h = (w.t1 - w.t0) / 3600.0
    ts = Float64[]
    qs = Float64[]
    good_time = 0.0
    switched = false
    for r in rows
        if r.quality == q_range_switch
            switched = true
            continue
        end
        q = r.flow_kg_h
        g = get(sc.engineer.range_gains, (sid, r.range_idx), nothing)
        if g !== nothing
            q = q / (1.0 + g)
        end
        push!(ts, r.t)
        push!(qs, q)
    end
    # 梯形积分 kg/h * s /3600
    m = 0.0
    for i in 2:length(ts)
        m += (qs[i] + qs[i-1]) / 2 * (ts[i] - ts[i-1]) / 3600.0
    end
    coverage = isempty(ts) ? 0.0 : (last(ts) - first(ts)) / (w.t1 - w.t0)
    missing_data = coverage < 0.90
    # 未确认增益的量程切换 -> 叠加仪表系统不确定度（见 UNCONFIRMED_GAIN_U）
    extra_gain = (switched && has_unconfirmed_gain(sc, sid)) ? UNCONFIRMED_GAIN_U : meter.gain_rel
    u = m * sqrt(meter.base_rel^2 + extra_gain^2)
    return IV(m, u), coverage, switched, missing_data
end

has_unconfirmed_gain(sc::Scenario, sid::String) =
    any(k -> k[1] == sid, keys(sc.engineer.range_gains)) == false &&
    any(r -> r.stream_id == sid && r.quality == q_range_switch, sc.mirror)

# ---------------- 样品/组成 ----------------

"""选取窗口内代表样品：取样时刻落在稳定段、结果在窗口关闭前到达、工程师接受时延。"""
function select_sample(sc::Scenario, sid::String, flags::Vector{String})
    w = sc.spec
    cands = filter(s -> s.stream_id == sid, sc.samples)
    pick = nothing
    for s in sort(cands; by=x -> x.taken_at)
        (s.taken_at < w.stable0 || s.taken_at > w.stable1) && continue
        s.received_at > w.t1 && continue
        get(sc.engineer.sample_delay_ok, sid, true) || continue
        pick = s
        break
    end
    if pick === nothing
        # 区分“晚到/不接受时延”与“无样品”
        late = findfirst(s -> s.stream_id == sid &&
                             (s.received_at > w.t1 ||
                              !get(sc.engineer.sample_delay_ok, sid, true)), cands)
        if late !== nothing
            push!(flags, "sample_late:" * sid)
        end
        push!(flags, "missing_stream_composition:" * sid)
        return nothing
    end
    return pick
end

"""组成基准归一化并核查干湿基混淆。
- basis=dry：湿基脂肪 = 干基脂肪 × 干物质湿基分数；
- 任何登记值/换算后湿基脂肪超出支路物理合理上限即标记 basis_mixup；
标记不静默“修正”数据，使用值照登记基准换算，由工程师复核。
返回 (fat_wet, solids_wet)。"""
function normalize_composition(s::LabSample, sid::String, flags::Vector{String})
    fat_wet = s.basis == dry ? s.fat * s.solids : s.fat
    maxf = get(PLAUS_FAT_MAX, sid, 1.0)
    if fat_wet > maxf || fat_wet < 0.0
        push!(flags, string("basis_mixup:", sid, " 湿基脂肪 ", round(100fat_wet;digits=3), "% 超出合理上限 ", round(100maxf;digits=2), "%"))
    elseif s.basis == dry && sid in ("skim", "raw", "product", "reflux") &&
           s.fat * s.solids > maxf
        push!(flags, "basis_mixup:" * sid)
    end
    return fat_wet, s.solids
end

# ---------------- 支路质量（含组分） ----------------

function branch_masses(sc::Scenario, flags::Vector{String})
    comps = Dict{String,LabSample}()
    out = BranchMass[]
    missing_streams = String[]
    for s in sc.streams
        sid = s.id
        m, coverage, switched, nodata = integrate_mass(sc, sid)
        if nodata
            push!(missing_streams, sid)
            push!(flags, "missing_stream_meter:" * sid)
            continue
        end
        if switched
            push!(flags, "range_switch:" * sid)
            if has_unconfirmed_gain(sc, sid)
                push!(flags, "gain_unconfirmed:" * sid)
            end
        end
        coverage < 0.98 && push!(flags, string("low_coverage:", sid, ":",
                                               round(Int, coverage * 100), "%"))
        sample = select_sample(sc, sid, flags)
        fat_wet = sol_wet = NaN
        fat_iv = solids_iv = IV(NaN, NaN)
        if sample !== nothing
            comps[sid] = sample
            fat_wet, sol_wet = normalize_composition(sample, sid, flags)
            fu = sample.basis == dry ? max(FAT_U[sid] * 2.0, abs(fat_wet) * 0.05) : FAT_U[sid]
            su = SOL_U[sid]
            # 组分质量区间：m*c，不确定度按相对传播
            fat_iv = compmass(m, IV(fat_wet, fu))
            solids_iv = compmass(m, IV(sol_wet, su))
        else
            push!(missing_streams, sid)
        end
        push!(out, BranchMass(sid, m, fat_iv, solids_iv, coverage, switched))
    end
    return out, comps, unique(missing_streams)
end

# ---------------- 罐持液 ----------------

function holdup_change(sc::Scenario, tank_id::String)
    h = sc.engineer.holdups
    i = findfirst(x -> x.tank_id == tank_id, h)
    i === nothing && return (0.0, 0.0, 0.0, true)
    x = h[i]
    return (x.end_kg - x.start_kg,
            x.fat_end - x.fat_start,
            x.solids_end - x.solids_start,
            x.registered)
end

# ---------------- 节点闭合 ----------------

function close_node(label, node_id, sc, branches, missing_comps; total=false)
    sm = IV(0.0, 0.0); sf = IV(0.0, 0.0); ss = IV(0.0, 0.0)
    comp_ok = true
    incident = String[]
    for b in branches
        s = total ? stream_sign(find_stream(sc, b.stream_id)) :
                    sign_at_node(find_stream(sc, b.stream_id), node_id)
        s == 0 && continue
        push!(incident, b.stream_id)
        sm += s * b.mass            # 质量闭合始终计入（缺组成不等于缺计量）
        if !isnan(b.fat.x)
            sf += s * b.fat
            ss += s * b.solids
        else
            comp_ok = false         # 该边界上存在缺组成样品的支路
        end
    end
    miss_here = filter(x -> x in incident && x in missing_comps, missing_comps)
    comp_present = isempty(miss_here)
    # 持液变化：边界内库存增加会使“进-出”残差为正，需减去 ΔH；
    # 节点闭合只取该节点罐；全厂取所有登记罐；未登记罐一律不参与账面平衡。
    for h in sc.engineer.holdups
        (!total && h.tank_id != node_id) && continue
        dm, df, dsol, registered = holdup_change(sc, h.tank_id)
        if !registered
            continue   # 未登记旧料不参与账面平衡，作为未计物流浮现
        end
        sm -= IV(dm, 0.0)
        if comp_present
            sf -= IV(df, 0.0)
            ss -= IV(dsol, 0.0)
        end
    end
    if !comp_present
        sf = IV(NaN, NaN); ss = IV(NaN, NaN)
    end
    NodeClosure(node_id, label, sm, sf, ss,
                contains0(sm) ? closed : open,
                comp_present ? (contains0(sf) ? closed : open) : inconclusive,
                comp_present ? (contains0(ss) ? closed : open) : inconclusive,
                sm, sf, ss, miss_here)
end

# ---------------- 主入口 ----------------

"""对情景执行核算，返回 WindowReport。"""
function reconcile(sc::Scenario; force::Bool=false)
    flags = String[]
    w = sc.spec

    # 1) 工程师必须确认稳定段
    stable = sc.engineer.stable_confirmed &&
             w.stable0 >= w.t0 && w.stable1 <= w.t1 && w.stable1 > w.stable0
    if !stable
        push!(flags, "unstable_window")
    end

    # 2) 回流跨批标记（边界处理在拓扑里：external_in=true）
    for s in sc.streams
        if s.is_reflux && s.crosses_batch
            push!(flags, "reflux_cross_batch:" * s.id)
        end
    end

    # 3) 未登记罐底旧料
    for h in sc.engineer.holdups
        if !h.registered && (h.end_kg - h.start_kg) != 0.0
            push!(flags, "unregistered_holdup:" * h.tank_id)
        end
    end

    branches, comps, missing = branch_masses(sc, flags)

    # 4) 节点闭合
    nodes = NodeClosure[]
    push!(nodes, close_node("离心分离机 进/出", "sep", sc, branches, missing))
    push!(nodes, close_node("回配罐 进/出", "blend", sc, branches, missing))
    total = close_node("全厂边界（含跨批回流外部输入）", "TOTAL", sc, branches, missing; total=true)

    # 5) 实际产品组成区间（湿基）：产品组分质量 / 产品质量
    pb = findfirst(b -> b.stream_id == "product", branches)
    if pb !== nothing && !isnan(branches[pb].fat.x)
        b = branches[pb]
        af = composition(b.fat, b.mass)
        asol = composition(b.solids, b.mass)
    else
        af = IV(NaN, NaN); asol = IV(NaN, NaN)
        push!(flags, "no_product_composition")
    end

    unique!(flags)
    return WindowReport(w, branches, nodes, total, flags, af, asol, missing, comps, stable)
end

"标记 -> 严重级别，供 UI/报告着色。"
flag_level(f) = startswith(f, "missing_stream") ? "高" :
                startswith(f, "unregistered") ? "高" :
                startswith(f, "unstable") ? "高" :
                startswith(f, "basis_mixup") ? "中" :
                startswith(f, "gain_unconfirmed") ? "中" :
                startswith(f, "sample_late") ? "中" :
                startswith(f, "reflux_cross") ? "信息" :
                startswith(f, "range_switch") ? "信息" : "中"
