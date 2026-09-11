# Plotly 展示：各支路干物质及脂肪闭合（质量区间、节点残差区间）。
# 输出自包含 HTML（plotly.js CDN）；无显示环境也可生成。
using JSON3

_short(sid) = sid

function _bar_trace(names, xs, los, his; label, color, dash=false)
    Dict("type" => "bar", "name" => label,
         "x" => names, "y" => xs,
         "error_y" => Dict("type" => "data",
                           "array" => [max(h - x, 0.0) for (h, x) in zip(his, xs)],
                           "arrayminus" => [max(x - l, 0.0) for (l, x) in zip(los, xs)],
                           "visible" => true, "thickness" => 2.5, "width" => 8),
         "marker" => Dict("color" => color))
end

"""图1：各支路质量/脂肪/干物质（k=2 误差棒）。"""
function branch_figure(rep::WindowReport)
    names = String[b.stream_id for b in rep.branches]
    names_zh = Dict("raw" => "原奶", "skim" => "脱脂乳", "cream" => "稀奶油回配",
                    "cream_out" => "稀奶油出品", "product" => "产品", "reflux" => "回流")
    labels = [get(names_zh, n, n) for n in names]
    mass = [b.mass.x for b in rep.branches]
    fat  = [b.fat.x for b in rep.branches]
    sol  = [b.solids.x for b in rep.branches]
    traces = [
        _bar_trace(labels, mass, [lo(b.mass) for b in rep.branches],
                   [hi(b.mass) for b in rep.branches]; label="质量 kg", color="#2c7fb8"),
        _bar_trace(labels, [isnan(v) ? 0 : v for v in fat],
                   [isnan(b.fat.x) ? 0 : lo(b.fat) for b in rep.branches],
                   [isnan(b.fat.x) ? 0 : hi(b.fat) for b in rep.branches];
                   label="脂肪 kg", color="#d95f0e"),
        _bar_trace(labels, [isnan(v) ? 0 : v for v in sol],
                   [isnan(b.solids.x) ? 0 : lo(b.solids) for b in rep.branches],
                   [isnan(b.solids.x) ? 0 : hi(b.solids) for b in rep.branches];
                   label="干物质 kg", color="#31a354"),
    ]
    layout = Dict("title" => Dict("text" => "各支路质量 / 脂肪 / 干物质（k=2 区间）"),
                  "barmode" => "group", "xaxis" => Dict("title" => "支路"),
                  "yaxis" => Dict("title" => "kg"))
    return traces, layout
end

"""图2：节点残差区间（含0线判定闭合），质量/脂肪/干物质分面。"""
function closure_figure(rep::WindowReport)
    cs = vcat(rep.nodes, [rep.total])
    labels = [c.label for c in cs]
    function errtraces(comp, color, title)
        xs = [isnan(comp(c).x) ? missing : comp(c).x for c in cs]
        us = [isnan(comp(c).u) ? 0 : comp(c).u for c in cs]
        [Dict("type" => "scatter", "mode" => "markers", "name" => title,
              "x" => labels, "y" => xs,
              "connectgaps" => false,
              "marker" => Dict("color" => color, "size" => 10),
              "error_y" => Dict("type" => "data",
                  "array" => us, "arrayminus" => us,
                  "thickness" => 2, "width" => 6))]
    end
    traces = vcat(
        errtraces(c -> c.residual_mass, "#2c7fb8", "质量残差"),
        errtraces(c -> c.residual_fat, "#d95f0e", "脂肪残差"),
        errtraces(c -> c.residual_solids, "#31a354", "干物质残差"))
    layout = Dict("title" => Dict("text" => "节点残差区间（误差棒跨 0 即闭合，k=2）"),
                  "xaxis" => Dict("title" => "边界节点"),
                  "yaxis" => Dict("title" => "残差 kg（进−出−Δ持液）", "zeroline" => true),
                  "shapes" => [Dict("type" => "line", "xref" => "paper",
                      "x0" => 0, "x1" => 1, "y0" => 0, "y1" => 0,
                      "line" => Dict("color" => "red", "dash" => "dash"))])
    return traces, layout
end

_html_wrap(traces, layout, divid) = """
<div id="$divid" style="width:1100px;height:520px"></div>
<script>
(function(){
  var data = $(JSON3.write(traces));
  var layout = $(JSON3.write(layout));
  if (window.Plotly) { Plotly.newPlot('$divid', data, layout); }
  else { document.getElementById('$divid').innerText =
    '离线环境未加载 plotly.js；数据见 DuckDB closures/branches 表。'; }
})();
</script>"""

"""生成自包含 HTML（CDN plotly.js）。"""
function write_plot_html(path::AbstractString, rep::WindowReport; title::AbstractString="乳脂回配核算")
    t1, l1 = branch_figure(rep)
    t2, l2 = closure_figure(rep)
    html = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>$title</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>body{font-family:system-ui,"Noto Sans CJK SC",sans-serif;margin:20px}
.bad{color:#b10} .ok{color:#070}</style></head><body>
<h1>$title <small>批次 $(rep.spec.batch_id)</small></h1>
<p>稳定段：$(Int(rep.spec.stable0))–$(Int(rep.spec.stable1)) s，窗口：$(Int(rep.spec.t0))–$(Int(rep.spec.t1)) s</p>
$(_html_wrap(t1, l1, "branches"))
$(_html_wrap(t2, l2, "closures"))
</body></html>"""
    write(path, html)
    return path
end
