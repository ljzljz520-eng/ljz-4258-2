# 现场流量与密度镜像：先转成 Apache Arrow 表，再供核算读取。
using Arrow: Arrow
using DataFrames

"""镜像采样向量 -> DataFrame（Arrow 友好列类型）。"""
function mirror_to_frame(samples::AbstractVector{FlowMirrorSample})
    DataFrame(
        t = Float64[s.t for s in samples],
        stream_id = String[s.stream_id for s in samples],
        flow_kg_h = Float64[s.flow_kg_h for s in samples],
        density_kg_m3 = Float64[s.density_kg_m3 for s in samples],
        range_idx = Int32[s.range_idx for s in samples],
        quality = String[replace(string(s.quality), "q_" => "") for s in samples],
    )
end

"""样品索引 -> DataFrame。"""
function samples_to_frame(ss::AbstractVector{LabSample})
    DataFrame(
        id = String[s.id for s in ss],
        stream_id = String[s.stream_id for s in ss],
        taken_at = Float64[s.taken_at for s in ss],
        received_at = Float64[s.received_at for s in ss],
        fat = Float64[s.fat for s in ss],
        solids = Float64[s.solids for s in ss],
        basis = String[s.basis == wet ? "wet" : "dry" for s in ss],
        delay_ok = Bool[s.delay_ok for s in ss],
    )
end

"""写 Arrow IPC 文件（镜像落盘/交换）。"""
write_arrow(path::AbstractString, df::AbstractDataFrame) =
    Arrow.write(path, df)

"""读 Arrow 文件为 DataFrame。"""
read_arrow(path::AbstractString) = DataFrame(Arrow.Table(path))

"""镜像帧 -> 采样向量。"""
function frame_to_mirror(df::AbstractDataFrame)
    qmap = Dict("good" => q_good, "range_switch" => q_range_switch,
                "stale" => q_stale, "missing" => q_missing,
                "overrange" => q_overrange)
    [FlowMirrorSample(row.t, row.stream_id, row.flow_kg_h, row.density_kg_m3,
                      Int(row.range_idx), get(qmap, String(row.quality), q_good))
     for row in eachrow(df)]
end

"""帧 -> 样品向量。"""
function frame_to_samples(df::AbstractDataFrame)
    [LabSample(row.id, row.stream_id, row.taken_at, row.received_at, row.fat,
               row.solids, String(row.basis) == "dry" ? dry : wet, Bool(row.delay_ok))
     for row in eachrow(df)]
end

"""在线脂肪仪读数 -> DataFrame（原始值，不做任何修正）。"""
function analyzer_to_frame(rs::AbstractVector{AnalyzerReading})
    DataFrame(
        t = Float64[r.t for r in rs],
        stream_id = String[r.stream_id for r in rs],
        fat_pct = Float64[r.fat_pct for r in rs],
        temp_c = Float64[r.temp_c for r in rs],
        quality = String[replace(string(r.quality), "q_" => "") for r in rs],
        tcomp_version = Int32[r.tcomp_version for r in rs],
    )
end

"""帧 -> 在线脂肪仪读数向量。"""
function frame_to_analyzer(df::AbstractDataFrame)
    qmap = Dict("good" => q_good, "range_switch" => q_range_switch,
                "stale" => q_stale, "missing" => q_missing,
                "overrange" => q_overrange)
    [AnalyzerReading(row.t, row.stream_id, row.fat_pct, row.temp_c,
                     get(qmap, String(row.quality), q_good), Int(row.tcomp_version))
     for row in eachrow(df)]
end
