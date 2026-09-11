#!/usr/bin/env julia
# 命令行入口（无头环境可用）：
#   julia bin/milkbalance.jl --demo                # 跑全部 S1..S10，输出到 data/
#   julia bin/milkbalance.jl --run S3              # 跑单个情景
#   julia bin/milkbalance.jl --run S1 --gain 0.08  # 工程师确认量程2增益修正
#   julia bin/milkbalance.jl --gui                 # 桌面 Gtk4 界面
using Pkg
Pkg.activate(normpath(joinpath(@__DIR__, "..")))
using MilkBalance

const DATADIR = joinpath(@__DIR__, "..", "data")
const DBPATH = joinpath(DATADIR, "milkbalance.duckdb")
const SCEN_IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")

help() = println("""用法:
  --demo                 核算 S1..S10 全部测试情景（Arrow+DuckDB+Plotly HTML+文本）
  --run <S1..S10> [--gain <小数>]  核算单个情景，可选量程增益修正
  --gui                  启动 Gtk4 图形界面（需要显示环境）
输出位于 data/：arrow/、plot_*.html、milkbalance.duckdb、report_*.txt
S6..S10 为在线脂肪仪偏差复核情景（仅评估校准状态，不修正在线原始值）。""")

function main(args)
    mkpath(DATADIR)
    isempty(args) || first(args) in ("-h", "--help") && return help()

    if first(args) == "--gui"
        MilkBalance.run_gui(; dbpath=DBPATH, outdir=DATADIR)
        return
    end

    if first(args) == "--demo"
        allok = true
        isfile(DBPATH) && rm(DBPATH)
        db = MilkBalance.open_db(DBPATH)
        try
            for id in SCEN_IDS
                r = MilkBalance.run_scenario(id; dbpath=DBPATH, outdir=DATADIR, db=db)
                write(joinpath(DATADIR, "report_$(id).txt"), r.text)
                println(r.text)
                ok, miss, present = MilkBalance.expect_flags_present(
                    r.report, r.scenario.expect_flags)
                rok, rmiss, rpresent = MilkBalance.expect_review_flags_present(
                    r.review, r.scenario.expect_review_flags)
                allok &= ok & rok
                println(">>> 期望标记检查 $(ok ? "通过" : "未通过（缺 $miss）")，实际：",
                        join(present, ","))
                isempty(r.scenario.expect_review_flags) ||
                    println(">>> 复核标记检查 $(rok ? "通过" : "未通过（缺 $rmiss）")，实际：",
                            join(rpresent, ","))
                println()
            end
        finally
            MilkBalance.DuckDB.DBInterface.close!(db)
        end
        println("全部产物见 data/ 目录（Arrow、DuckDB、HTML、TXT）。",
                allok ? "" : " 注意：有标记检查未通过。")
        return
    end

    if first(args) == "--run"
        length(args) < 2 && error("--run 需要情景号 S1..S10")
        id = args[2]
        gain = nothing
        length(args) >= 4 && args[3] == "--gain" && (gain = parse(Float64, args[4]))
        r = MilkBalance.run_scenario(id; dbpath=DBPATH, outdir=DATADIR,
                                     gain_correction=gain)
        print(r.text)
        write(joinpath(DATADIR, "report_$(id).txt"), r.text)
        return
    end
    error("未知参数：", join(args, " "))
end

main(ARGS)
