"""charts.py — 외부 CDN 없이 로컬에서 바로 작동하는 인터랙티브 SVG 차트 생성기

1. 레이더 차트 (Radar Chart): 4대 사고 단계 + 대화 깊이 + 오류 점검 등 다차원 역량 비교
2. 선버스트 차트 (Sunburst Chart): 학교급 → 4대 사고 단계 → 생각 변화(유지/수정/확장) 3단 계층 분포
"""
import html
import json
import math


def build_radar_chart_html(
    title: str,
    axes: list[str],
    series: list[dict],
    max_val: float = 100.0,
    height: int = 440,
) -> str:
    """첨부 이미지 1 스타일의 인터랙티브 레이더(거미줄) 차트 HTML을 반환한다.

    series 항목 예시:
      {"name": "1차 해석", "color": "#5470C6", "values": [72, 65, 68, 70, 60, 40]}
    """
    n = len(axes)
    cx, cy = 260, 225
    radius = 148
    levels = 5

    # 1. 동심 다각형 격자 및 눈금
    grid_svgs = []
    for lv in range(levels, 0, -1):
        r = radius * (lv / levels)
        pts = []
        for i in range(n):
            ang = -math.pi / 2 + (2 * math.pi * i / n)
            pts.append(f"{cx + r * math.cos(ang):.1f},{cy + r * math.sin(ang):.1f}")
        fill = "#F8FAFC" if lv % 2 == 1 else "#FFFFFF"
        grid_svgs.append(
            f'<polygon points="{" ".join(pts)}" fill="{fill}" stroke="#CBD5E1" stroke-width="1"/>'
        )
        tick_val = int(round(max_val * lv / levels))
        grid_svgs.append(
            f'<text x="{cx - 6}" y="{cy - r + 12:.1f}" text-anchor="end" '
            f'font-size="10.5" fill="#64748B">{tick_val}</text>'
        )
    grid_svgs.append(f'<text x="{cx - 6}" y="{cy + 4}" text-anchor="end" font-size="10.5" fill="#64748B">0</text>')

    # 2. 방사선 축 및 축 라벨
    axis_svgs = []
    for i, label in enumerate(axes):
        ang = -math.pi / 2 + (2 * math.pi * i / n)
        x2 = cx + radius * math.cos(ang)
        y2 = cy + radius * math.sin(ang)
        axis_svgs.append(f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#CBD5E1" stroke-width="1"/>')

        lx = cx + (radius + 24) * math.cos(ang)
        ly = cy + (radius + 22) * math.sin(ang)
        cos_a = math.cos(ang)
        anchor = "middle" if abs(cos_a) < 0.25 else ("start" if cos_a > 0 else "end")
        dy = 4 if math.sin(ang) > 0.3 else (-4 if math.sin(ang) < -0.5 else 3)
        axis_svgs.append(
            f'<text x="{lx:.1f}" y="{ly + dy:.1f}" text-anchor="{anchor}" '
            f'font-size="12.5" font-weight="600" fill="#1E293B">{html.escape(label)}</text>'
        )

    # 3. 시리즈 폴리곤 및 포인트 + 상단 범례
    series_svgs = []
    legend_btns = []
    for s_idx, s in enumerate(series):
        color = s["color"]
        name = html.escape(s["name"])
        vals = s["values"]
        pts = []
        circles = []
        for i, val in enumerate(vals):
            clamped = max(0.0, min(float(val), max_val))
            r = radius * (clamped / max_val) if max_val > 0 else 0
            ang = -math.pi / 2 + (2 * math.pi * i / n)
            px = cx + r * math.cos(ang)
            py = cy + r * math.sin(ang)
            pts.append(f"{px:.1f},{py:.1f}")
            tip = html.escape(f"{s['name']} · {axes[i]}: {val:.1f}")
            circles.append(
                f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="#FFFFFF" stroke="{color}" '
                f'stroke-width="2.5" class="pt" data-tip="{tip}"/>'
            )

        series_svgs.append(
            f'<g class="radar-series" id="series-{s_idx}">'
            f'<polygon points="{" ".join(pts)}" fill="{color}" fill-opacity="0.16" '
            f'stroke="{color}" stroke-width="2.4" stroke-linejoin="round"/>'
            + "".join(circles)
            + "</g>"
        )
        legend_btns.append(
            f'<button class="leg-btn" data-idx="{s_idx}" onclick="toggleSeries({s_idx})">'
            f'<span class="swatch" style="background:{color};"></span>{name}</button>'
        )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; }}
  body {{ margin: 0; padding: 6px; background: transparent; }}
  .card {{ background: #fff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 10px 12px 6px; position: relative; }}
  .title {{ font-size: 14px; font-weight: 700; color: #0F172A; text-align: center; margin-bottom: 6px; }}
  .legend {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-bottom: 2px; }}
  .leg-btn {{ display: inline-flex; align-items: center; gap: 6px; border: 1px solid #E2E8F0; background: #F8FAFC;
              border-radius: 999px; padding: 3px 10px; font-size: 12px; color: #334155; cursor: pointer; transition: opacity .15s; }}
  .leg-btn.off {{ opacity: 0.35; text-decoration: line-through; }}
  .swatch {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  svg {{ display: block; margin: 0 auto; max-width: 100%; height: auto; }}
  .pt {{ cursor: pointer; transition: r .12s; }}
  .pt:hover {{ r: 7.5; }}
  #tip {{ position: fixed; pointer-events: none; background: rgba(15, 23, 42, 0.92); color: #fff;
          padding: 6px 10px; border-radius: 8px; font-size: 12px; display: none; z-index: 99; white-space: nowrap; }}
</style>
</head>
<body>
<div class="card">
  <div class="title">{html.escape(title)}</div>
  <div class="legend">{"".join(legend_btns)}</div>
  <svg viewBox="0 0 520 420" width="520" height="{height - 76}">
    {"".join(grid_svgs)}
    {"".join(axis_svgs)}
    {"".join(series_svgs)}
  </svg>
  <div id="tip"></div>
</div>
<script>
  function toggleSeries(idx) {{
    const g = document.getElementById("series-" + idx);
    const btn = document.querySelector('.leg-btn[data-idx="' + idx + '"]');
    const hidden = g.style.display === "none";
    g.style.display = hidden ? "inline" : "none";
    btn.classList.toggle("off", !hidden);
  }}
  const tip = document.getElementById("tip");
  document.querySelectorAll(".pt").forEach(el => {{
    el.addEventListener("mousemove", e => {{
      tip.textContent = el.getAttribute("data-tip");
      tip.style.display = "block";
      tip.style.left = Math.min(window.innerWidth - 190, e.clientX + 12) + "px";
      tip.style.top = Math.max(8, e.clientY - 32) + "px";
    }});
    el.addEventListener("mouseleave", () => {{ tip.style.display = "none"; }});
  }});
</script>
</body>
</html>"""


def _arc_path(cx: float, cy: float, r_in: float, r_out: float, a0: float, a1: float) -> str:
    """SVG 도넛 조각(arc) 경로 문자열을 생성한다."""
    # 전체 원(2*pi)에 가까울 때 SVG 아크 소실 방지
    if a1 - a0 >= 2 * math.pi - 1e-4:
        a1 = a0 + 2 * math.pi - 1e-3
    large = 1 if (a1 - a0) > math.pi else 0
    x0_out, y0_out = cx + r_out * math.cos(a0), cy + r_out * math.sin(a0)
    x1_out, y1_out = cx + r_out * math.cos(a1), cy + r_out * math.sin(a1)
    x1_in, y1_in = cx + r_in * math.cos(a1), cy + r_in * math.sin(a1)
    x0_in, y0_in = cx + r_in * math.cos(a0), cy + r_in * math.sin(a0)
    return (
        f"M {x0_out:.2f},{y0_out:.2f} "
        f"A {r_out:.2f},{r_out:.2f} 0 {large} 1 {x1_out:.2f},{y1_out:.2f} "
        f"L {x1_in:.2f},{y1_in:.2f} "
        f"A {r_in:.2f},{r_in:.2f} 0 {large} 0 {x0_in:.2f},{y0_in:.2f} Z"
    )


def build_sunburst_chart_html(
    title: str,
    tree: list[dict],
    height: int = 440,
) -> str:
    """첨부 이미지 2 스타일의 3단 계층 선버스트 차트 HTML을 반환한다.

    tree 구조:
      [
        {
          "name": "초등학교", "color": "#5CB3F6", "mid_color": "#8CCBF8", "outer_color": "#C6E5FC",
          "children": [
            {"name": "해석", "children": [{"name": "유지", "value": 4}, {"name": "수정", "value": 2}, {"name": "확장", "value": 7}]},
            ...
          ]
        }, ...
      ]
    """
    cx, cy = 260, 212
    rings = [(44, 102), (104, 152), (154, 194)]

    def sum_node(node: dict) -> int:
        if "children" in node and node["children"]:
            return sum(sum_node(c) for c in node["children"])
        return int(node.get("value", 0))

    total = sum(sum_node(n) for n in tree)
    if total <= 0:
        return "<div style='padding:24px;text-align:center;color:#64748B;'>표시할 데이터가 없습니다.</div>"

    slices = []
    labels = []

    def add_slice(r_in, r_out, a0, a1, color, path_str, val, short_label, font_size, text_color):
        if val <= 0 or a1 <= a0:
            return
        pct = val / total * 100
        d = _arc_path(cx, cy, r_in, r_out, a0, a1)
        tip = html.escape(f"{path_str} : {val}문항 ({pct:.1f}%)")
        slices.append(
            f'<path d="{d}" fill="{color}" stroke="#FFFFFF" stroke-width="1.4" '
            f'class="sb-slice" data-tip="{tip}" data-title="{html.escape(path_str)}" '
            f'data-val="{val}문항 ({pct:.1f}%)"/>'
        )
        span = a1 - a0
        if span >= 0.17:
            mid = (a0 + a1) / 2
            rm = (r_in + r_out) / 2
            tx = cx + rm * math.cos(mid)
            ty = cy + rm * math.sin(mid)
            labels.append(
                f'<text x="{tx:.1f}" y="{ty + 3.5:.1f}" text-anchor="middle" '
                f'font-size="{font_size}" font-weight="600" fill="{text_color}" '
                f'pointer-events="none">{html.escape(short_label)}</text>'
            )

    cur_a1 = -math.pi / 2
    for lv1 in tree:
        v1 = sum_node(lv1)
        if v1 <= 0:
            continue
        span1 = 2 * math.pi * (v1 / total)
        a1_end = cur_a1 + span1
        c1 = lv1["color"]
        c2 = lv1["mid_color"]
        c3 = lv1["outer_color"]
        add_slice(rings[0][0], rings[0][1], cur_a1, a1_end, c1, lv1["name"], v1, lv1["name"], 11.5, "#FFFFFF")

        cur_a2 = cur_a1
        for lv2 in lv1.get("children", []):
            v2 = sum_node(lv2)
            if v2 <= 0:
                continue
            span2 = span1 * (v2 / v1)
            a2_end = cur_a2 + span2
            short2 = lv2["name"].replace("근거·추론", "근거").replace("반론·평가", "반론").replace("나와 연결하기", "연결")
            add_slice(
                rings[1][0], rings[1][1], cur_a2, a2_end, c2,
                f"{lv1['name']} › {lv2['name']}", v2, short2, 10.2, "#0F172A",
            )

            cur_a3 = cur_a2
            for lv3 in lv2.get("children", []):
                v3 = sum_node(lv3)
                if v3 <= 0:
                    continue
                span3 = span2 * (v3 / v2)
                a3_end = cur_a3 + span3
                add_slice(
                    rings[2][0], rings[2][1], cur_a3, a3_end, c3,
                    f"{lv1['name']} › {lv2['name']} › {lv3['name']}", v3, lv3["name"], 9.2, "#334155",
                )
                cur_a3 = a3_end
            cur_a2 = a2_end
        cur_a1 = a1_end

    legend_html = "".join(
        f'<span class="leg-item"><span class="sw" style="background:{n["color"]};"></span>{html.escape(n["name"])}</span>'
        for n in tree if sum_node(n) > 0
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; }}
  body {{ margin: 0; padding: 6px; background: transparent; }}
  .card {{ background: #fff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 10px 12px 6px; position: relative; }}
  .title {{ font-size: 14px; font-weight: 700; color: #0F172A; text-align: center; margin-bottom: 4px; }}
  .sub {{ font-size: 11px; color: #64748B; text-align: center; margin-bottom: 6px; }}
  .legend {{ display: flex; justify-content: center; gap: 12px; margin-bottom: 2px; font-size: 11.5px; color: #334155; }}
  .leg-item {{ display: inline-flex; align-items: center; gap: 5px; }}
  .sw {{ width: 10px; height: 10px; border-radius: 3px; display: inline-block; }}
  svg {{ display: block; margin: 0 auto; max-width: 100%; height: auto; }}
  .sb-slice {{ cursor: pointer; transition: opacity .15s; }}
  .sb-slice:hover {{ opacity: 0.82; }}
  #tip {{ position: fixed; pointer-events: none; background: rgba(15, 23, 42, 0.92); color: #fff;
          padding: 6px 10px; border-radius: 8px; font-size: 12px; display: none; z-index: 99; white-space: nowrap; }}
</style>
</head>
<body>
<div class="card">
  <div class="title">{html.escape(title)}</div>
  <div class="sub">안쪽: 학교급 → 중간: 4대 사고 단계 → 바깥쪽: 생각 변화(유지·수정·확장)</div>
  <div class="legend">{legend_html}</div>
  <svg viewBox="0 0 520 420" width="520" height="{height - 86}">
    {"".join(slices)}
    {"".join(labels)}
    <circle cx="{cx}" cy="{cy}" r="42" fill="#FFFFFF"/>
    <text id="c-top" x="{cx}" y="{cy - 4}" text-anchor="middle" font-size="11" font-weight="700" fill="#0F172A">전체</text>
    <text id="c-bot" x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="11.5" font-weight="600" fill="#2563EB">{total}문항</text>
  </svg>
  <div id="tip"></div>
</div>
<script>
  const tip = document.getElementById("tip");
  const cTop = document.getElementById("c-top");
  const cBot = document.getElementById("c-bot");
  const defaultBot = "{total}문항";
  document.querySelectorAll(".sb-slice").forEach(el => {{
    el.addEventListener("mousemove", e => {{
      tip.textContent = el.getAttribute("data-tip");
      tip.style.display = "block";
      tip.style.left = Math.min(window.innerWidth - 220, e.clientX + 12) + "px";
      tip.style.top = Math.max(8, e.clientY - 32) + "px";
      const parts = el.getAttribute("data-title").split(" › ");
      cTop.textContent = parts[parts.length - 1];
      cBot.textContent = el.getAttribute("data-val").split(" ")[0];
    }});
    el.addEventListener("mouseleave", () => {{
      tip.style.display = "none";
      cTop.textContent = "전체";
      cBot.textContent = defaultBot;
    }});
  }});
</script>
</body>
</html>"""
