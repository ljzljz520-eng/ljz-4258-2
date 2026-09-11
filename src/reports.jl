# 文本核算报告：实际组成区间、未计物流、标记、闭合结论。
# 明确不输出标准化比例建议、不含任何分离机控制指令。

function fmt(z::IV)
    isnan(z.x) && return "  无可用组成  "
    @sprintf("%+.2f ± %.2f kg [%+.2f, %+.2f]", z.x, z.u, lo(z), hi(z))
end
fmtpct(z::IV) = isnan(z.x) ? "无" :
    @sprintf("%.3f%% ± %.3f pp [%.3f%%, %.3f%%]",
             100z.x, 100z.u, 100lo(z), 100hi(z))

function text_report(sc::Scenario, rep::WindowReport)
    io = IOBuffer()
    println(io, "========== 乳脂回配物料/组分核算 ==========")
    println(io, "情景: ", sc.id, " ", sc.title)
    println(io, "批次: ", sc.spec.batch_id,
            "  共同窗口 ", Int(sc.spec.t0), "-", Int(sc.spec.t1),
            " s  稳定段 ", Int(sc.spec.stable0), "-", Int(sc.spec.stable1), " s")
    println(io, "稳定段已由工程师确认: ", rep.stable ? "是" : "否")
    println(io)
    println(io, "-- 各支路窗口积分（k=2） --")
    for b in rep.branches
        @printf(io, "%-8s 质量 %.1f ± %.1f kg  覆盖 %.0f%%%s\n",
                b.stream_id, b.mass.x, b.mass.u, 100b.coverage,
                b.switched ? "  [含量程切换]" : "")
        if !isnan(b.fat.x)
            @printf(io, "         脂肪 %8.2f ± %.2f kg   干物质 %8.2f ± %.2f kg\n",
                    b.fat.x, b.fat.u, b.solids.x, b.solids.u)
        else
            println(io, "         脂肪/干物质：缺少有效样品，未计入组分闭合")
        end
    end
    println(io)
    println(io, "-- 节点闭合（进−出−Δ持液，含0即闭合） --")
    for c in rep.nodes
        _node_line(io, c)
    end
    _node_line(io, rep.total; is_total=true)
    if rep.total.status_mass === open
        t = rep.total.residual_mass
        println(io, @sprintf("        => 全厂未计物料（质量）%+.1f kg，区间 [%+.1f, %+.1f] kg",
                             t.x, lo(t), hi(t)))
    end
    println(io)
    println(io, "-- 实际产品组成（湿基，测量区间，非标准化目标） --")
    println(io, "实际脂肪: ", fmtpct(rep.actual_fat_interval))
    println(io, "实际干物质: ", fmtpct(rep.actual_solids_interval))
    if !isempty(rep.missing_streams)
        println(io, "未计物流(缺计量或组成): ", join(rep.missing_streams, ", "))
    else
        println(io, "未计物流: 无")
    end
    println(io)
    println(io, "-- 数据质量标记 --")
    if isempty(rep.flags)
        println(io, "无")
    else
        for f in rep.flags
            @printf(io, "[%s] %s\n", flag_level(f), explain_flag(f))
        end
    end
    println(io)
    println(io, "说明：本程序仅做边界内核算与不确定度报告，")
    println(io, "      不推荐标准化/回配比例，也不向离心分离机发送控制指令。")
    return String(take!(io))
end

function _node_line(io, c; is_total=false)
    tag = is_total ? "[全厂]" : "[节点]"
    nm = Dict(closed => "闭合", open => "未闭合", inconclusive => "组成不全")
    cm, cf, cs = nm[c.status_mass], nm[c.status_fat], nm[c.status_solids]
    @printf(io, "%s %-30s 质量 %s  脂肪 %s  干物质 %s\n", tag, c.label, cm, cf, cs)
    @printf(io, "        残差 质量 %s\n", fmt(c.residual_mass))
    if !isnan(c.residual_fat.x)
        @printf(io, "        残差 脂肪 %s\n", fmt(c.residual_fat))
        @printf(io, "        残差 干物 %s\n", fmt(c.residual_solids))
    else
        println(io, "        残差 脂肪/干物：组成缺失，无法判定（支路：",
                join(c.missing_composition, ", "), "）")
    end
end

const FLAG_TEXT = Dict(
    "range_switch" => "流量计量程发生切换：切换瞬态样本已从积分中剔除",
    "gain_unconfirmed" => "量程切换后的增益修正未经工程师确认，已按 ±2% 附加仪表系统不确定度",
    "sample_late" => "样品结果晚于窗口关闭到达或时延未被接受",
    "missing_stream_composition" => "支路缺少窗口/稳定段内有效组成样品",
    "missing_stream_meter" => "支路窗口内缺少有效流量镜像",
    "reflux_cross_batch" => "回流跨越批次边界，按外部输入计入共同边界",
    "unregistered_holdup" => "罐底存量未登记：账面平衡中浮现为未计物流",
    "basis_mixup" => "脂肪结果疑似干/湿基混淆（已按登记基准换算，请核对录入）",
    "low_coverage" => "窗口内有效积分覆盖低于 98%",
    "unstable_window" => "工程师未确认稳定段或窗口参数非法",
    "no_product_composition" => "无产品组成，无法给出实际组成区间",
)

explain_flag(f) = begin
    base = split(f, ':')[1]
    txt = get(FLAG_TEXT, base, f)
    return startswith(f, base * ":") ? txt * "（" * join(split(f, ':')[2:end], ":") * "）" : txt
end
