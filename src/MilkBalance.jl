module MilkBalance
# 原奶离心分离 -> 稀奶油/脱脂乳 -> 回配目标乳脂：共同边界核算应用。
# 边界声明：
#  * 进出流量、脂肪检测、罐底残留、回流必须落在同一计算窗口（共同边界）内；
#  * 现场流量与密度镜像先转 Apache Arrow 表，流程拓扑/计算窗口/样品索引/结果落 DuckDB；
#  * Plotly 展示各支路干物质及脂肪闭合；
#  * 工程师确认稳定段、样品时延、罐内持液；程序计算实际组成区间、未计物流与
#    扩展不确定度(k=2)；
#  * 程序不推荐标准化/回配比例，也不向离心分离机发送任何控制指令。

using Dates
using Printf
using Random
using Statistics
using UUIDs

using Arrow
using DataFrames
using DuckDB
using JSON3

include("types.jl")
include("intervals.jl")
include("scenarios.jl")
include("arrowio.jl")
include("engine.jl")
include("analyzer.jl")
include("db.jl")
include("plots.jl")
include("reports.jl")
include("pipeline.jl")
include("gui.jl")   # Gtk4 延迟 require，无头环境安全

export IV, lo, hi, contains0, compmass, composition,
       Node, NodeKind, Stream, MeterSpec, FlowMirrorSample, LabSample, FatBasis,
       ClosureStatus, Quality, TankHoldup, WindowSpec, EngineerInputs, RangeState,
       BranchMass, NodeClosure, WindowReport, Scenario,
       AnalyzerReading, AnalyzerSpec, DeviationPoint, CalStatus,
       AnalyzerStreamReview, AnalyzerReview,
       scenario, all_scenarios,
       reconcile, integrate_mass, branch_masses,
       review_analyzers, match_sample_to_analyzer,
       detect_stale_runs, flow_segment_boundaries,
       mirror_to_frame, samples_to_frame, analyzer_to_frame, write_arrow, read_arrow,
       frame_to_mirror, frame_to_samples, frame_to_analyzer,
       open_db, save_scenario, save_report, save_review, register_arrow, list_batches,
       write_plot_html, analyzer_figure, text_report, analyzer_review_text,
       flag_level, explain_flag,
       persist_mirror, persist_analyzer, run_scenario,
       expect_flags_present, expect_review_flags_present,
       run_gui, gtk_available

end # module
