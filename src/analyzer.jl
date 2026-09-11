# 在线脂肪仪偏差复核：把同期实验室结果按样品时延匹配到在线读数，
# 给出偏差趋势与校准状态。工程边界（与核算引擎相同严格）：
#   * 不自动修正、不回写任何在线原始读数；
#   * 复核结果不进入物料/脂肪闭合（reconcile 不读取本模块任何结果）；
#   * 无法可靠匹配的点只展示、不计入趋势与校准统计，并说明原因。

using Statistics: mean

# ---------------- 读数体检 ----------------

"""检测在线读数中的恒值冻结段（清洗后保持旧值的特征），返回 [(t_start, t_end)]。
连续 ≥ min_run 个相邻读数与段首读数之差不超过 atol 即判为冻结。
即使镜像未打 q_stale 标记，也能从数据本身识别“保持旧值”。"""
function detect_stale_runs(readings; min_run::Int=4, atol::Float64=1e-9)
    rs = sort!(collect(readings); by=r -> r.t)
    ranges = Tuple{Float64,Float64}[]
    n = length(rs)
    n < min_run && return ranges
    i = 1
    while i <= n
        j = i
        while j + 1 <= n && abs(rs[j + 1].fat_pct - rs[i].fat_pct) <= atol
            j += 1
        end
        if j - i + 1 >= min_run
            push!(ranges, (rs[i].t, rs[j].t))
        end
        i = j + 1
    end
    return ranges
end

in_stale_range(ranges, t) = any(ab -> ab[1] - 1e-9 <= t <= ab[2] + 1e-9, ranges)

"""流量段边界（秒）：量程切换点、切换瞬态、或相邻流量阶跃超过 step_tol 的时刻。
一只实验室样经样品时延回推后若匹配窗跨过边界，则该样对应两个流量段。"""
function flow_segment_boundaries(mirror, sid; step_tol::Float64=0.15)
    rows = sort!([r for r in mirror if r.stream_id == sid]; by=r -> r.t)
    bnds = Float64[]
    for i in 2:length(rows)
        a, b = rows[i - 1], rows[i]
        if b.range_idx != a.range_idx ||
           a.quality == q_range_switch || b.quality == q_range_switch ||
           abs(b.flow_kg_h - a.flow_kg_h) > step_tol * max(abs(a.flow_kg_h), eps())
            push!(bnds, b.t)
        end
    end
    return unique!(sort!(bnds))
end

# ---------------- 时延匹配 ----------------

"""把一只实验室样按样品时延匹配到在线读数，返回 DeviationPoint。
匹配窗 = [取样时刻-时延 ± 半窗]。窗内读数按质量剔除：
q_missing 丢弃；q_stale/冻结段、超量程（质量标记或读数>量程上限）剔除后
用其余有效读数取均值。全部无效则该点无法匹配（online/deviation = NaN）。
非稳态取样、跨流量段、温度补偿版本混合的点只展示、不计入统计。
本函数只读数据，不修正任何在线原始值。"""
function match_sample_to_analyzer(s::LabSample, spec::AnalyzerSpec, readings,
                                  stale_ranges, bounds, w::WindowSpec)
    ta = s.taken_at - spec.transport_delay
    lo_, hi_ = ta - spec.match_halfwin, ta + spec.match_halfwin
    inwin = [r for r in readings if lo_ - 1e-9 <= r.t <= hi_ + 1e-9]
    reasons = String[]
    used = true
    if s.taken_at < w.stable0 || s.taken_at > w.stable1
        push!(reasons, "nonsteady_sample")
        used = false
    end
    if any(b -> lo_ < b < hi_, bounds)
        push!(reasons, "spans_flow_segments")
        used = false
    end
    lab_fat = s.basis == dry ? s.fat * s.solids : s.fat
    good = AnalyzerReading[]
    n_stale = 0
    n_over = 0
    for r in inwin
        if r.quality == q_missing
            continue
        elseif r.quality == q_stale || in_stale_range(stale_ranges, r.t)
            n_stale += 1
        elseif r.quality == q_overrange || r.fat_pct > spec.range_max
            n_over += 1
        else
            push!(good, r)
        end
    end
    n_stale > 0 && push!(reasons, "stale_excluded:$n_stale")
    n_over > 0 && push!(reasons, "overrange_excluded:$n_over")
    if isempty(good)
        isempty(inwin) && push!(reasons, "no_readings")
        (n_stale > 0 && n_over == 0) && push!(reasons, "stale_hold")
        (n_over > 0 && n_stale == 0) && push!(reasons, "overrange_all")
        return DeviationPoint(s.id, s.stream_id, s.taken_at, ta, NaN, lab_fat,
                              NaN, false, reasons, 0)
    end
    # 温度补偿版本混合的窗：只保留多数版本读数，且该点不计入统计
    vers = [r.tcomp_version for r in good]
    uvers = unique(vers)
    ver = uvers[argmax([count(==(v), vers) for v in uvers])]
    if length(uvers) > 1
        push!(reasons, "tcomp_mixed_window")
        used = false
        good = [r for r in good if r.tcomp_version == ver]
    end
    online = mean(r.fat_pct for r in good)
    return DeviationPoint(s.id, s.stream_id, s.taken_at, ta, online, lab_fat,
                          online - lab_fat, used, reasons, ver)
end

# ---------------- 趋势与校准状态 ----------------

"""最小二乘斜率（每小时），点数不足或横坐标无展布返回 NaN。"""
function _slope_per_h(ts, ys)
    n = length(ts)
    n < 2 && return NaN
    mt = sum(ts) / n
    my = sum(ys) / n
    den = sum((t - mt)^2 for t in ts)
    den <= 0 && return NaN
    return sum((t - mt) * (y - my) for (t, y) in zip(ts, ys)) / den * 3600.0
end

"""校准状态判定：任一温度补偿版本平均偏差超允差、或版本间偏差差超允差 -> 可疑；
计入点 ≥3 且窗内趋势漂移量超允差 -> 漂移；无计入点 -> 数据不足。"""
function _cal_status(used, version_mean_dev, slope_per_h, tol, window_h)
    isempty(used) && return cal_insufficient
    vals = collect(values(version_mean_dev))
    any(v -> abs(v) > tol, vals) && return cal_suspect
    length(vals) > 1 && (maximum(vals) - minimum(vals) > tol) && return cal_suspect
    if length(used) >= 3 && !isnan(slope_per_h) && abs(slope_per_h) * window_h > tol
        return cal_drift
    end
    return cal_ok
end

_has_reason(p::DeviationPoint, key) =
    any(r -> r == key || startswith(r, key * ":"), p.reasons)

"""复核一台分析仪（一条支路）：匹配全部同期实验室样，统计偏差趋势与校准状态。"""
function review_stream(spec::AnalyzerSpec, sc::Scenario)
    sid = spec.stream_id
    w = sc.spec
    readings = sort!([r for r in sc.analyzer_readings if r.stream_id == sid]; by=r -> r.t)
    stale_ranges = detect_stale_runs(readings)
    bounds = flow_segment_boundaries(sc.mirror, sid)
    samples = sort!([s for s in sc.samples if s.stream_id == sid &&
                     w.t0 <= s.taken_at <= w.t1]; by=s -> s.taken_at)
    points = [match_sample_to_analyzer(s, spec, readings, stale_ranges, bounds, w)
              for s in samples]
    flags = String[]
    any(p -> _has_reason(p, "nonsteady_sample"), points) &&
        push!(flags, "analyzer_nonsteady_sample:" * sid)
    any(p -> _has_reason(p, "stale_hold"), points) &&
        push!(flags, "analyzer_stale_hold:" * sid)
    any(p -> _has_reason(p, "overrange_excluded") || _has_reason(p, "overrange_all"),
        points) && push!(flags, "analyzer_overrange_excluded:" * sid)
    any(p -> _has_reason(p, "spans_flow_segments"), points) &&
        push!(flags, "analyzer_spans_flow_segments:" * sid)
    any(p -> _has_reason(p, "tcomp_mixed_window"), points) &&
        push!(flags, "analyzer_tcomp_mixed:" * sid)
    any(p -> _has_reason(p, "no_readings"), points) &&
        push!(flags, "analyzer_no_match:" * sid)

    used = [p for p in points if p.used && !isnan(p.deviation)]
    n = length(used)
    mean_dev = n > 0 ? mean(p.deviation for p in used) : NaN
    slope = _slope_per_h([p.taken_at for p in used], [p.deviation for p in used])
    vers = sort!(unique([p.tcomp_version for p in used]))
    vmean = Dict(v => mean(p.deviation for p in used if p.tcomp_version == v)
                 for v in vers)
    length(vers) > 1 && push!(flags, "analyzer_tcomp_change:" * sid)
    status = _cal_status(used, vmean, slope, spec.tol, (w.t1 - w.t0) / 3600.0)
    status == cal_suspect && push!(flags, "analyzer_cal_suspect:" * sid)
    status == cal_drift && push!(flags, "analyzer_cal_drift:" * sid)
    status == cal_insufficient && push!(flags, "analyzer_cal_insufficient:" * sid)
    return AnalyzerStreamReview(sid, points, n, mean_dev, slope, status, vers,
                                vmean, spec.tol, flags)
end

"""复核整批全部登记分析仪。结果仅供校准状态评估，不进入物料闭合。"""
function review_analyzers(sc::Scenario)
    streams = [review_stream(spec, sc) for spec in sc.analyzer_specs]
    flags = isempty(streams) ? String[] : unique!(vcat([s.flags for s in streams]...))
    return AnalyzerReview(sc.spec.batch_id, streams, flags)
end
