# 区间运算：均值 ± 扩展不确定度（k=2）
# 不确定度按分量绝对值/平方和传播；残差闭合判据为 0 ∈ 区间。

import Base: +, -, *, /, ==, zero, isapprox

+(a::IV, b::IV) = IV(a.x + b.x, _rss(a.u, b.u))
-(a::IV, b::IV) = IV(a.x - b.x, _rss(a.u, b.u))
-(a::IV) = IV(-a.x, a.u)
*(a::IV, b::IV) = IV(a.x * b.x, abs(a.x * b.x) * sqrt((a.u/max(abs(a.x),eps()))^2 + (b.u/max(abs(b.x),eps()))^2))
*(k::Real, a::IV) = IV(Float64(k) * a.x, abs(Float64(k)) * a.u)
*(a::IV, k::Real) = k * a
/(a::IV, b::IV) = IV(a.x / b.x, abs(a.x / b.x) * sqrt((a.u/max(abs(a.x),eps()))^2 + (b.u/max(abs(b.x),eps()))^2))
==(a::IV, b::IV) = a.x == b.x && a.u == b.u
zero(::Type{IV}) = IV(0.0, 0.0)
zero(::IV) = zero(IV)
isapprox(a::IV, b::IV; kw...) = isapprox(a.x, b.x; kw...)

_rss(u1::Real, u2::Real) = sqrt(u1 * u1 + u2 * u2)
_rss(v) = sqrt(sum(abs2, v))

contains0(z::IV; tol::Real=0.0) = lo(z) <= tol && hi(z) >= -tol
shift(z::IV, dx::Real) = IV(z.x + dx, z.u)

"""按已知系统偏差平移（量程切换增益、旧料未登记等），不确定度宽度不变。"""
correct(z::IV, correction::Real) = shift(z, correction)

"""组分质量：m * c，质量与组成独立，按相对不确定度传播。"""
compmass(m::IV, c::IV) = m * c

"""由两个独立量组成区间反推（除法）。"""
composition(comp::IV, m::IV) = comp / m

function Base.show(io::IO, z::IV)
    print(io, @sprintf("%+.3f ± %.3f [%.3f, %.3f]", z.x, z.u, lo(z), hi(z)))
end
