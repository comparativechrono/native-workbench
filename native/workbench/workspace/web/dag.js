/* Stable-ID DAG projection. Every data-dependency rank occupies exactly one row. */
function renderBranchDAG(host, graph, Graph, onSelect, options = {}) {
  if (host._branchDAGCleanup) host._branchDAGCleanup();
  host.replaceChildren();
  const nodeById = new Map((graph.nodes || []).map(node => [node.id, node]));
  const sourceById = new Map((graph.sources || []).map(source => [source.id, source]));
  const tools = Graph.tools;
  const displayId = id => Graph.displayId ? Graph.displayId(id) : /^step-(\d+)$/.test(id) ? 'S' + id.match(/\d+$/)[0] : /^input-(\d+)$/.test(id) ? 'I' + id.match(/\d+$/)[0] : id;
  const getSource = id => Graph.getSource ? Graph.getSource(graph, id) : sourceById.get(id) || (nodeById.has(id) ? { id, type: tools[nodeById.get(id).tool].output.type } : null);
  const inputRefs = node => [...new Set(Object.values(node.inputs || {}).flat().filter(Boolean))];
  const inputIds = node => [...new Set(inputRefs(node).map(Graph.producer))];
  const isReference = id => sourceById.get(id)?.type === 'reference';
  const nodeName = id => {
    if (sourceById.has(id)) return sourceById.get(id).label || displayId(id);
    const node = nodeById.get(id);
    if (!node) return displayId(id);
    if (Graph.nodeLabel) return Graph.nodeLabel(graph, id);
    return node.label || tools[node.tool].name;
  };
  let ordered;
  try { ordered = Graph.topo(graph).map(node => typeof node === 'string' ? nodeById.get(node) : node).filter(Boolean); }
  catch (_) { ordered = [...graph.nodes]; }
  const included = new Set(ordered.map(node => node.id));
  ordered.push(...graph.nodes.filter(node => !included.has(node.id)));
  const usedIds = new Set(ordered.flatMap(inputIds));
  const activeSources = [...sourceById.values()].filter(source => usedIds.has(source.id) && !isReference(source.id));
  const rankById = new Map(activeSources.map(source => [source.id, 0]));
  for (const node of ordered) {
    const parents = inputIds(node).filter(id => !isReference(id) && rankById.has(id));
    rankById.set(node.id, parents.length ? Math.max(...parents.map(id => rankById.get(id))) + 1 : 1);
  }
  const rankGroups = new Map();
  const items = [...activeSources.map(source => ({id: source.id, source})), ...ordered.map(node => ({id: node.id, node}))];
  for (const item of items) {
    const rank = rankById.get(item.id);
    if (!rankGroups.has(rank)) rankGroups.set(rank, []);
    rankGroups.get(rank).push(item);
  }
  const stage = document.createElement('div');
  stage.className = 'dag-stage';
  const canvas = document.createElement('div');
  canvas.className = 'dag-canvas';
  stage.append(canvas);
  const key = document.createElement('div');
  key.className = 'dag-key';
  stage.append(key);
  host.append(stage);
  const svgNS = 'http://www.w3.org/2000/svg';
  const markerId = 'ranked-arrow-' + (renderBranchDAG._serial = (renderBranchDAG._serial || 0) + 1);
  let observer, scheduled = 0, lastWidth = -1, destroyed = false;
  const text = (tag, className, content) => {
    const el = document.createElement(tag);
    el.className = className;
    el.textContent = content;
    return el;
  };
  const select = id => { if (typeof onSelect === 'function') onSelect(id); };
  function referenceChip(id) {
    const chip = text('button', 'dag-reference-chip', displayId(id) + ' · ' + nodeName(id));
    chip.type = 'button';
    chip.dataset.referenceSource = id;
    chip.dataset.tooltip = 'Shared reference input: ' + nodeName(id);
    chip.setAttribute('aria-label', `Reference ${displayId(id)}, ${nodeName(id)}. Show input.`);
    if (id === options.selectedId) chip.classList.add('dag-highlight-chip');
    chip.addEventListener('click', () => select(id));
    return chip;
  }
  // Project centres onto an ordered, non-overlapping row while retaining barycentres.
  function placeCentres(desired, separation, minimum, maximum) {
    const blocks = [];
    desired.forEach((value, index) => {
      blocks.push({first: index, last: index, sum: value - index * separation, count: 1});
      while (blocks.length > 1) {
        const a = blocks[blocks.length - 2], b = blocks[blocks.length - 1];
        if (a.sum / a.count <= b.sum / b.count) break;
        blocks.splice(-2, 2, {first: a.first, last: b.last, sum: a.sum + b.sum, count: a.count + b.count});
      }
    });
    const result = [];
    const upper = maximum - (desired.length - 1) * separation;
    for (const block of blocks) {
      const centre = Math.max(minimum, Math.min(upper, block.sum / block.count));
      for (let i = block.first; i <= block.last; i++) result[i] = centre + i * separation;
    }
    return result;
  }
  function addKeyEntry(item) {
    const row = document.createElement('div');
    row.className = 'dag-key-row';
    row.dataset.keyId = item.id;
    if (item.id === options.selectedId) row.classList.add('dag-highlight');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'dag-key-button';
    button.append(text('strong', 'dag-key-id', displayId(item.id)));
    const details = document.createElement('span');
    details.className = 'dag-key-details';
    details.append(text('span', 'dag-key-name', nodeName(item.id)));
    if (item.node) {
      const parents = inputIds(item.node).filter(id => !isReference(id));
      details.append(text('span', 'dag-key-inputs', parents.length ? 'From ' + parents.map(displayId).join(' + ') : 'Inputs not connected'));
    } else details.append(text('span', 'dag-key-inputs', 'Input · ' + item.source.type));
    button.append(details);
    button.addEventListener('click', () => select(item.id));
    row.append(button);
    if (item.node) {
      const refs = inputIds(item.node).filter(isReference);
      if (refs.length) {
        const refRow = document.createElement('div');
        refRow.className = 'dag-key-references';
        refs.forEach(id => refRow.append(referenceChip(id)));
        row.append(refRow);
      }
    }
    key.append(row);
  }
  function draw() {
    if (destroyed || !canvas.isConnected) return;
    const width = Math.floor(canvas.getBoundingClientRect().width);
    if (width < 1) return;
    lastWidth = width;
    canvas.replaceChildren();
    key.replaceChildren();
    key.hidden = true;
    const rects = new Map(), previousX = new Map(), compactItems = [];
    const gutter = 17;
    const usable = Math.max(1, width - gutter * 2);
    let rowIndex = 0;
    for (const rank of [...rankGroups.keys()].sort((a, b) => a - b)) {
      const rankItems = rankGroups.get(rank).slice();
      const preferred = item => {
        const xs = item.node ? inputIds(item.node).filter(id => !isReference(id) && previousX.has(id)).map(id => previousX.get(id)) : [];
        return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : width / 2;
      };
      // Stable sorting keeps sibling order deterministic when they share a parent.
      rankItems.sort((a, b) => preferred(a) - preferred(b));
      const gap = rankItems.length > 3 ? 7 : 12;
      const cardWidth = Math.min(225, Math.max(1, (usable - gap * (rankItems.length - 1)) / rankItems.length));
      const compact = cardWidth < 89;
      const desired = rankItems.map((item, index) => item.source && rankItems.length > 1 ? width / 2 + (index - (rankItems.length - 1) / 2) * (cardWidth + gap) : preferred(item));
      const xs = placeCentres(desired, cardWidth + gap, gutter + cardWidth / 2, width - gutter - cardWidth / 2);
      const row = document.createElement('div');
      row.className = 'dag-rank';
      row.dataset.rank = rank;
      row.setAttribute('aria-label', 'Dependency level ' + rank);
      canvas.append(row);
      for (let index = 0; index < rankItems.length; index++) {
        const item = rankItems[index];
        previousX.set(item.id, xs[index]);
        const card = document.createElement('div');
        card.className = 'dag-card ' + (item.node ? 'dag-operation' : 'dag-source') + (compact ? ' dag-compact' : '');
        card.dataset.dagId = item.id;
        card.dataset.nodeId = item.id;
        card.dataset.rank = rank;
        card.style.width = cardWidth + 'px';
        card.style.left = xs[index] - cardWidth / 2 + 'px';
        if (item.id === options.selectedId) card.classList.add('dag-highlight');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'dag-node-button';
        const parents = item.node ? inputRefs(item.node).map(id => getSource(id)?.label || displayId(id)) : [];
        button.setAttribute('aria-label', `${displayId(item.id)}, ${nodeName(item.id)}. ${parents.length ? 'Inputs from ' + parents.join('; ') + '. ' : ''}Show ${item.node ? 'step' : 'input'}.`);
        button.dataset.tooltip = displayId(item.id) + ' · ' + nodeName(item.id);
        button.append(text('span', 'dag-node-id', displayId(item.id)));
        if (!compact) {
          button.append(text('strong', 'dag-title', nodeName(item.id)));
          if (item.node && tools[item.node.tool].name !== nodeName(item.id)) button.append(text('span', 'dag-subtitle', tools[item.node.tool].name));
          if (item.source) button.append(text('span', 'dag-subtitle', item.source.type));
        }
        button.addEventListener('click', () => select(item.id));
        card.append(button);
        if (item.node && !compact) inputIds(item.node).filter(isReference).forEach(id => card.append(referenceChip(id)));
        if (compact) compactItems.push(item);
        row.append(card);
        rects.set(item.id, {card, row: rowIndex, rank});
      }
      const height = Math.max(...[...row.children].map(card => card.getBoundingClientRect().height));
      row.style.height = Math.ceil(height) + 'px';
      for (const card of row.children) card.style.height = Math.ceil(height) + 'px';
      rowIndex++;
    }
    if (!items.length) {
      canvas.append(text('p', 'dag-empty', 'Add a tool to start your graph.'));
      return;
    }
    if (compactItems.length) {
      key.hidden = false;
      key.append(text('p', 'dag-key-heading', 'Step key'));
      compactItems.forEach(addKeyEntry);
    }
    const base = canvas.getBoundingClientRect();
    for (const rect of rects.values()) {
      const box = rect.card.getBoundingClientRect();
      Object.assign(rect, {left: box.left - base.left, right: box.right - base.left, top: box.top - base.top, bottom: box.bottom - base.top, x: box.left + box.width / 2 - base.left});
    }
    const svg = document.createElementNS(svgNS, 'svg');
    svg.classList.add('dag-edges');
    svg.setAttribute('width', width);
    svg.setAttribute('height', Math.ceil(base.height));
    svg.setAttribute('viewBox', `0 0 ${width} ${Math.ceil(base.height)}`);
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    const defs = document.createElementNS(svgNS, 'defs');
    for (const highlighted of [false, true]) {
      const marker = document.createElementNS(svgNS, 'marker');
      marker.id = markerId + (highlighted ? '-selected' : '');
      marker.setAttribute('viewBox', '0 0 8 8');
      marker.setAttribute('refX', '7'); marker.setAttribute('refY', '4');
      marker.setAttribute('markerWidth', '5'); marker.setAttribute('markerHeight', '5');
      marker.setAttribute('orient', 'auto');
      const arrow = document.createElementNS(svgNS, 'path');
      arrow.setAttribute('d', 'M 1 1 L 7 4 L 1 7 Z');
      arrow.classList.add(highlighted ? 'dag-arrow-selected' : 'dag-arrow');
      marker.append(arrow); defs.append(marker);
    }
    svg.append(defs);
    let skipped = 0;
    for (const node of ordered) {
      const target = rects.get(node.id);
      if (!target) continue;
      for (const parentId of inputIds(node)) {
        if (isReference(parentId)) continue;
        const source = rects.get(parentId);
        if (!source) continue;
        const startY = source.bottom + 1, endY = target.top - 3;
        let d;
        if (target.row === source.row + 1) {
          const middle = (startY + endY) / 2;
          d = `M ${source.x} ${startY} C ${source.x} ${middle} ${target.x} ${middle} ${target.x} ${endY}`;
        } else {
          const side = skipped % 2, lane = Math.floor(skipped / 2) % 4;
          const busX = side ? width - 3 - lane * 3 : 3 + lane * 3;
          skipped++;
          d = `M ${source.x} ${startY} V ${source.bottom + 12} H ${busX} V ${target.top - 14} H ${target.x} V ${endY}`;
        }
        const path = document.createElementNS(svgNS, 'path');
        path.classList.add('dag-edge');
        const highlighted = options.selectedId === node.id || options.selectedId === parentId;
        if (highlighted) path.classList.add('dag-highlight-edge');
        path.dataset.from = parentId; path.dataset.to = node.id;
        path.setAttribute('d', d);
        path.setAttribute('marker-end', `url(#${markerId}${highlighted ? '-selected' : ''})`);
        const title = document.createElementNS(svgNS, 'title');
        title.textContent = inputRefs(node).filter(ref => Graph.producer(ref) === parentId).map(ref => `${getSource(ref)?.label || parentId} → ${displayId(node.id)} ${nodeName(node.id)}`).join('; ');
        path.append(title); svg.append(path);
      }
    }
    canvas.prepend(svg);
  }
  function schedule() { cancelAnimationFrame(scheduled); scheduled = requestAnimationFrame(draw); }
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => { if (Math.floor(canvas.getBoundingClientRect().width) !== lastWidth) schedule(); });
    observer.observe(canvas);
  } else window.addEventListener('resize', schedule);
  host._branchDAGCleanup = () => {
    destroyed = true;
    cancelAnimationFrame(scheduled);
    if (observer) observer.disconnect(); else window.removeEventListener('resize', schedule);
  };
  draw(); schedule();
  return host._branchDAGCleanup;
}
