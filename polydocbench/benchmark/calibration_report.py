"""Offline Plotly calibration report backed by inspected aggregate/pair rows."""

from __future__ import annotations

import html
import json
from pathlib import Path


def write_calibration_report(output: Path, plan, summaries: list[dict], pairs: list[dict], pilot) -> None:
    from PIL import Image
    from plotly.offline import get_plotlyjs

    from .calibration import calibration_page_id

    by_condition = {(calibration_page_id(record), record.profile): record for record in pilot.selection.records}
    examples = []
    ranked = sorted((pair for pair in pairs if pair["paired"]),
                    key=lambda p: p["noisy_metrics"]["micro_CER"] - p["clean_metrics"]["micro_CER"], reverse=True)
    chosen = set()
    directory = output / "examples"
    directory.mkdir(exist_ok=True)
    for pair in ranked:
        if pair["base_page_id"] in chosen:
            continue
        chosen.add(pair["base_page_id"])
        clean = by_condition[(pair["base_page_id"], "clean")]
        noisy = by_condition[(pair["base_page_id"], pair["profile"])]
        gt = json.loads((output / "dataset" / clean.image_gt.path).read_text(encoding="utf-8"))
        lines = [element for page in gt["pages"] for container in page["containers"]
                 for element in container.get("elements", []) if element["type"] == "text_line"]
        box = lines[0]["bbox"]
        names = []
        for label, record in (("clean", clean), ("noisy", noisy)):
            with Image.open(output / "dataset" / record.image.path) as image:
                x, y = max(0, int(box["x"]) - 8), max(0, int(box["y"]) - 8)
                crop = image.crop((x, y, min(image.width, x + 1000), min(image.height, y + 320))).convert("RGB")
                crop.thumbnail((900, 300))
                name = f"example_{len(examples)}_{label}.png"
                crop.save(directory / name)
                names.append(f"examples/{name}")
        delta = 100 * (pair["noisy_metrics"]["micro_CER"] - pair["clean_metrics"]["micro_CER"])
        title = html.escape(f"{pair['language']}/{pair['article_id']}/{pair['template']} - {pair['operation']} L{pair['level']}")
        examples.append(f'<figure><h3>{title}</h3><div class="images"><img src="{names[0]}" alt="Clean fixed crop">'
                        f'<img src="{names[1]}" alt="Noisy fixed crop"></div><figcaption>Page CER delta: {delta:+.2f} pp</figcaption></figure>')
        if len(examples) == 3:
            break
    scopes = sorted({(row["dimension"], row["group"]) for row in summaries}, key=lambda v: (v[0] != "overall", v))
    options = "".join(f'<option value="{i}">{html.escape(d + ": " + g)}</option>' for i, (d, g) in enumerate(scopes))
    effects = "".join(f'<option value="{html.escape(s.operation)}">{html.escape(s.operation)}</option>' for s in plan.spec.sweeps)
    payload = json.dumps({"rows": summaries, "scopes": scopes}, allow_nan=False).replace("<", "\\u003c")
    scope = "Reviewed-family development split" if plan.split == "dev" else "Engineering pilot / unassigned historical sources"
    languages = sorted({r.language for r in plan.selection.records})
    templates = sorted({r.template for r in plan.selection.records})
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PolyDocBench Noise Calibration</title>
<style>
*{box-sizing:border-box}body{margin:0;font:15px system-ui,sans-serif;letter-spacing:0;color:#20292b;background:#f7f9fa}
header,main{max-width:1400px;margin:auto;padding:22px}header{border-bottom:2px solid #247780}h1{font-size:28px;margin:0 0 12px}
h2{font-size:21px;margin:24px 0 12px}h3{font-size:15px;margin:0 0 12px;overflow-wrap:anywhere}
p{line-height:1.5}a{color:#146b9b}.links,.controls{display:flex;gap:18px;flex-wrap:wrap;margin:18px 0}
label{display:grid;gap:5px}select{font:inherit;max-width:100%;padding:6px;border:1px solid #aebcc2;background:white}
.chart{height:410px;width:100%}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:9px;border-bottom:1px solid #d9e1e5;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}
figure{margin:14px 0;padding:16px 0;border-top:1px solid #d9e1e5}.images{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.images img{width:100%;aspect-ratio:3.1;object-fit:contain;background:white}figcaption{color:#52636a;margin-top:8px}
.scope{color:#52636a}.warning{border-left:3px solid #bd8c24;padding-left:12px}
@media(max-width:650px){header,main{padding:14px}.images{grid-template-columns:1fr}.chart{height:360px}select{width:100%}.controls label{width:100%}}
</style></head><body>"""
    page += f'<header><h1>PolyDocBench Noise Calibration</h1><p>{html.escape(scope)}</p>'
    page += f'<p class="scope">{len(plan.selection.records)} base pages &middot; {len(pilot.selection.records)} images &middot; '
    page += f'{html.escape(", ".join(languages))} &middot; {len(templates)} templates &middot; {plan.spec.dpi} DPI</p>'
    page += '<p class="warning">Exploratory measurements. No confidence intervals or automatic severity approval. '
    page += 'Seed repeats are not independent pages. Curves use complete page cohorts; failures remain in the ledger.</p>'
    page += '<nav class="links"><a href="calibration_summary.csv">Aggregate CSV</a><a href="paired_results.jsonl">Paired rows</a>'
    page += '<a href="run/results.jsonl">Full result ledger</a><a href="calibration_plan.json">Frozen plan</a>'
    page += '<a href="validation_report.json">Validation</a></nav></header><main><div class="controls">'
    page += f'<label>Effect<select id="effect">{effects}</select></label><label>Scope<select id="scope">{options}</select></label>'
    page += '<label>Metric<select id="metric"><option value="micro_CER">micro CER</option><option value="micro_WER">micro WER</option>'
    page += '<option value="line_F1">Line F1</option></select></label></div><p id="coverage" class="scope"></p>'
    page += '<div id="absolute" class="chart"></div><div id="delta" class="chart"></div><div class="scroll"><table>'
    page += '<thead><tr><th>Level / value</th><th>Selected pages</th><th>Complete pages</th><th>Available pairs</th>'
    page += '<th>Curve pairs</th><th>Expected pairs</th><th>Clean</th><th>Noisy</th><th>Delta</th></tr></thead><tbody id="values"></tbody></table></div>'
    page += '<h2>Illustrative Page CER Changes</h2><p class="scope">Selected by largest signed CER delta after evaluation; fixed top-text crops, not localized error boxes.</p>'
    page += "".join(examples)
    page += '<p class="scope">Protocol 0.2 &middot; Noise 0.3 &middot; insertion-aware micro aggregation &middot; no inference of real-scanner realism</p></main>'
    page += f'<script>{get_plotlyjs()}</script><script id="data" type="application/json">{payload}</script>'
    page += """<script>
const data=JSON.parse(document.getElementById('data').textContent);
const effect=document.getElementById('effect'),scope=document.getElementById('scope'),metric=document.getElementById('metric');
const pct=x=>x===null?'n/a':(100*x).toFixed(2)+'%';
function draw(){
 const selected=data.scopes[Number(scope.value)],m=metric.value;
 const rows=data.rows.filter(r=>r.operation===effect.value&&r.dimension===selected[0]&&r.group===selected[1]).sort((a,b)=>a.level-b.level);
 const x=rows.map(r=>r.value),clean=rows.map(r=>r['clean_'+m]),noisy=rows.map(r=>r['noisy_'+m]);
 const extra=rows.map(r=>[r.level,r.complete_base_pages,r.curve_pairs,r.expected_pairs]);
 const title=m==='line_F1'?'Line F1':m==='micro_CER'?'micro CER':'micro WER';
 const base={margin:{l:68,r:24,t:55,b:110},paper_bgcolor:'#f7f9fa',plot_bgcolor:'white',font:{family:'system-ui,sans-serif',size:13},
   legend:{orientation:'h',y:-0.35,x:0},xaxis:{title:{text:rows[0].parameter},autorange:effect.value==='faded_ink'?'reversed':true,tickmode:'array',tickvals:x},
   yaxis:{title:{text:title},tickformat:'.0%',rangemode:'tozero',gridcolor:'#e3e8eb'},hovermode:'closest'};
 const config={responsive:true,displaylogo:false};
 const hover='value=%{x}<br>score=%{y:.4f}<br>level=%{customdata[0]}<br>complete pages=%{customdata[1]}<br>curve pairs=%{customdata[2]}/%{customdata[3]}<extra>%{fullData.name}</extra>';
 Plotly.react('absolute',[{x,y:clean,customdata:extra,name:'Clean (same cohort)',mode:'lines+markers',line:{color:'#586970',dash:'dash'},hovertemplate:hover},
   {x,y:noisy,customdata:extra,name:'Noisy',mode:'lines+markers',line:{color:'#177fa3'},hovertemplate:hover}],{...base,title:{text:title+' - '+effect.value,font:{size:16}}},config);
 const scale=m==='line_F1'?1:100;
 Plotly.react('delta',[{x,y:rows.map(r=>r['delta_'+m]===null?null:r['delta_'+m]*scale),name:'Noisy - clean',mode:'lines+markers',line:{color:'#b78322'},customdata:extra,
   hovertemplate:'value=%{x}<br>delta=%{y:.3f}<br>complete pages=%{customdata[1]}<extra></extra>'}],
   {...base,showlegend:false,margin:{...base.margin,b:65},title:{text:'Paired '+title+' Change',font:{size:16}},yaxis:{...base.yaxis,title:{text:m==='line_F1'?'Delta F1 score':'Delta '+title+' (pp)'},tickformat:'.2f'},
   shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:0,y1:0,line:{color:'#586970',dash:'dot',width:1}}]},config);
 document.getElementById('coverage').textContent=rows[0].complete_base_pages+'/'+rows[0].selected_base_pages+' complete pages; '+rows[0].source_families+' source families (inferred if unreviewed).';
 const tbody=document.getElementById('values');tbody.replaceChildren();
 rows.forEach(r=>{const tr=document.createElement('tr');const values=['L'+r.level+' / '+r.value,r.selected_base_pages,r.complete_base_pages,r.available_pairs,r.curve_pairs,r.expected_pairs,
    pct(r['clean_'+m]),pct(r['noisy_'+m]),r['delta_'+m]===null?'n/a':(100*r['delta_'+m]).toFixed(2)+(m==='line_F1'?' score *100':' pp')];
   values.forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.appendChild(td)});tbody.appendChild(tr)});
}
[effect,scope,metric].forEach(control=>control.addEventListener('change',draw));draw();
</script></body></html>"""
    (output / "dashboard.html").write_text(page, encoding="utf-8")
