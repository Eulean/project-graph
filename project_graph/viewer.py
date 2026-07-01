from __future__ import annotations

import json

def viewer_html(nodes: list[dict], edges: list[dict], title: str) -> str:
    payload = json.dumps({"nodes": nodes, "edges": edges}, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4efe4;
      --panel: rgba(255,255,255,0.82);
      --text: #1f2933;
      --muted: #667085;
      --line: rgba(27, 67, 50, 0.22);
      --folder: #c97a44;
      --file: #215a6d;
      --accent: #1b4332;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(201,122,68,0.20), transparent 30%),
        radial-gradient(circle at bottom right, rgba(33,90,109,0.18), transparent 28%),
        var(--bg);
    }}
    .shell {{
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }}
    .panel {{
      padding: 18px;
      background: var(--panel);
      backdrop-filter: blur(14px);
      border-right: 1px solid rgba(0,0,0,0.06);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 1.3rem;
    }}
    p, label, input, button, select {{
      font: inherit;
    }}
    .muted {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    input, select {{
      width: 100%;
      padding: 10px 12px;
      margin: 8px 0 14px;
      border-radius: 10px;
      border: 1px solid rgba(0,0,0,0.12);
      background: rgba(255,255,255,0.9);
    }}
    .details {{
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid rgba(0,0,0,0.08);
      font-size: 0.92rem;
      line-height: 1.5;
      white-space: pre-wrap;
    }}
    canvas {{
      width: 100%;
      height: 100vh;
      display: block;
    }}
    .legend {{
      display: flex;
      gap: 10px;
      margin-top: 14px;
      font-size: 0.86rem;
      color: var(--muted);
    }}
    .swatch {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      display: inline-block;
      margin-right: 6px;
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="panel">
      <h1>{title}</h1>
      <p class="muted">Local graph viewer for cached project structure. Filter by node name, then click a node to inspect its neighborhood.</p>
      <label for="search">Filter nodes</label>
      <input id="search" type="text" placeholder="folder, file, module">
      <label for="kind">Node type</label>
      <select id="kind">
        <option value="all">All</option>
        <option value="folder">Folders</option>
        <option value="file">Files</option>
      </select>
      <div class="legend">
        <span><span class="swatch" style="background: var(--folder)"></span>Folder</span>
        <span><span class="swatch" style="background: var(--file)"></span>File</span>
      </div>
      <div id="details" class="details">Select a node to inspect it.</div>
    </aside>
    <main>
      <canvas id="graph"></canvas>
    </main>
  </div>
  <script>
    const payload = {payload};
    const nodes = payload.nodes.map((node, index) => ({{
      ...node,
      x: Math.cos(index * 0.6) * (160 + (index % 9) * 20),
      y: Math.sin(index * 0.6) * (160 + (index % 7) * 16),
      vx: 0,
      vy: 0
    }}));
    const nodeMap = new Map(nodes.map(node => [node.id, node]));
    const edges = payload.edges
      .map(edge => ({{
        ...edge,
        sourceNode: nodeMap.get(edge.source),
        targetNode: nodeMap.get(edge.target)
      }}))
      .filter(edge => edge.sourceNode && edge.targetNode);
    const neighbors = new Map(nodes.map(node => [node.id, new Set()]));
    for (const edge of edges) {{
      neighbors.get(edge.source).add(edge.target);
      neighbors.get(edge.target).add(edge.source);
    }}

    const canvas = document.getElementById("graph");
    const ctx = canvas.getContext("2d");
    const details = document.getElementById("details");
    const search = document.getElementById("search");
    const kind = document.getElementById("kind");
    let selected = null;
    let hovered = null;

    function resize() {{
      const ratio = window.devicePixelRatio || 1;
      canvas.width = canvas.clientWidth * ratio;
      canvas.height = canvas.clientHeight * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }}

    function visible(node) {{
      const term = search.value.trim().toLowerCase();
      const kindValue = kind.value;
      if (kindValue !== "all" && node.type !== kindValue) return false;
      if (!term) return true;
      return node.id.toLowerCase().includes(term) || node.label.toLowerCase().includes(term);
    }}

    function draw() {{
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(width / 2, height / 2);

      for (const edge of edges) {{
        if (!visible(edge.sourceNode) || !visible(edge.targetNode)) continue;
        const focus = selected && (edge.source === selected.id || edge.target === selected.id);
        ctx.strokeStyle = focus ? "rgba(27,67,50,0.55)" : "rgba(27,67,50,0.18)";
        ctx.lineWidth = focus ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(edge.sourceNode.x, edge.sourceNode.y);
        ctx.lineTo(edge.targetNode.x, edge.targetNode.y);
        ctx.stroke();
      }}

      for (const node of nodes) {{
        if (!visible(node)) continue;
        const focus = selected && (node.id === selected.id || neighbors.get(selected.id).has(node.id));
        const radius = node.type === "folder" ? 6 : 4;
        ctx.beginPath();
        ctx.fillStyle = node.type === "folder" ? "#c97a44" : "#215a6d";
        ctx.globalAlpha = selected ? (focus ? 1 : 0.18) : 0.88;
        ctx.arc(node.x, node.y, radius + (hovered === node ? 2 : 0), 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }}

      ctx.restore();
      requestAnimationFrame(tick);
    }}

    function tick() {{
      for (let i = 0; i < nodes.length; i += 1) {{
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j += 1) {{
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const distSq = Math.max(dx * dx + dy * dy, 0.01);
          const force = 1200 / distSq;
          const fx = dx * force * 0.0006;
          const fy = dy * force * 0.0006;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }}
      }}
      for (const edge of edges) {{
        const dx = edge.targetNode.x - edge.sourceNode.x;
        const dy = edge.targetNode.y - edge.sourceNode.y;
        const distance = Math.max(Math.hypot(dx, dy), 0.01);
        const spring = (distance - 54) * 0.0009;
        const fx = (dx / distance) * spring;
        const fy = (dy / distance) * spring;
        edge.sourceNode.vx += fx;
        edge.sourceNode.vy += fy;
        edge.targetNode.vx -= fx;
        edge.targetNode.vy -= fy;
      }}
      for (const node of nodes) {{
        node.vx *= 0.92;
        node.vy *= 0.92;
        node.x += node.vx;
        node.y += node.vy;
      }}
      draw();
    }}

    function pickNode(event) {{
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left - canvas.clientWidth / 2;
      const y = event.clientY - rect.top - canvas.clientHeight / 2;
      hovered = null;
      for (const node of nodes) {{
        if (!visible(node)) continue;
        const radius = node.type === "folder" ? 8 : 6;
        if (Math.hypot(node.x - x, node.y - y) <= radius) {{
          hovered = node;
        }}
      }}
      canvas.style.cursor = hovered ? "pointer" : "default";
    }}

    function renderDetails(node) {{
      const direct = [...neighbors.get(node.id)].slice(0, 12);
      const lines = [
        node.id,
        "",
        "type: " + node.type,
      ];
      if (node.ext) lines.push("ext: " + node.ext);
      if (node.lines) lines.push("lines: " + node.lines);
      lines.push("");
      lines.push("neighbors:");
      lines.push(...(direct.length ? direct.map(item => "- " + item) : ["- none"]));
      details.textContent = lines.join("\\n");
    }}

    canvas.addEventListener("mousemove", pickNode);
    canvas.addEventListener("click", () => {{
      selected = hovered;
      if (selected) renderDetails(selected);
      else details.textContent = "Select a node to inspect it.";
    }});
    window.addEventListener("resize", resize);
    search.addEventListener("input", () => {{
      selected = null;
      details.textContent = "Select a node to inspect it.";
    }});
    kind.addEventListener("change", () => {{
      selected = null;
      details.textContent = "Select a node to inspect it.";
    }});

    resize();
    tick();
  </script>
</body>
</html>
"""

