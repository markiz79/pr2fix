from collections import deque
from xml.etree import ElementTree as elementtree


SVG_NAMESPACE = 'http://www.w3.org/2000/svg'
NODE_HEIGHT = 48
ROW_GAP = 46
COLUMN_GAP = 140
MARGIN = 70
MIN_WIDTH = 190
CHAR_WIDTH = 9
TEXT_PADDING = 40


def mermaid_label(name):
    return ''.join(char if char.isalnum() or char in '-_.'
                   else f'#{ord(char)};' for char in name)


def mermaid_text(graph):
    nodes = {name: f'n{index}' for index, name in enumerate(graph)}
    lines = ['flowchart LR']
    for name, node in nodes.items():
        label = mermaid_label(name)
        lines.append(f'    {node}["{label}"]')
    for name, dependencies in graph.items():
        for dependency in dependencies or []:
            lines.append(f'    {nodes[name]} --> {nodes[dependency]}')
    lines.append('    classDef boundary stroke-dasharray: 5 5')
    for name, dependencies in graph.items():
        if dependencies is None:
            lines.append(f'    class {nodes[name]} boundary')
    return '\n'.join(lines) + '\n'


def node_levels(graph):
    levels = {}
    for start in graph:
        if start in levels:
            continue
        levels[start] = 0
        queue = deque([start])
        while queue:
            name = queue.popleft()
            for neighbor in graph[name] or []:
                if neighbor not in levels:
                    levels[neighbor] = levels[name] + 1
                    queue.append(neighbor)
    return levels


def layout_graph(graph):
    levels = node_levels(graph)
    width = max([MIN_WIDTH] + [len(name) * CHAR_WIDTH + TEXT_PADDING
                              for name in graph])
    rows = {}
    positions = {}
    for name, level in levels.items():
        row = rows.get(level, 0)
        positions[name] = (MARGIN + level * (width + COLUMN_GAP),
                           MARGIN + row * (NODE_HEIGHT + ROW_GAP))
        rows[level] = row + 1
    canvas_width = 2 * MARGIN + (max(levels.values(), default=0) + 1) * (
        width + COLUMN_GAP
    ) - COLUMN_GAP
    canvas_height = 2 * MARGIN + max(rows.values(), default=1) * (
        NODE_HEIGHT + ROW_GAP
    )
    return positions, width, canvas_width, canvas_height


def svg_element(parent, tag, attributes=None, text=None):
    element = elementtree.SubElement(parent, tag, attributes or {})
    element.text = text
    return element


def edge_path(start, end, width):
    x, y = start
    target_x, target_y = end
    y += NODE_HEIGHT / 2
    target_y += NODE_HEIGHT / 2
    if start == end:
        right = x + width
        return (f'M {right} {y - 10} C {right + 65} {y - 65}, '
                f'{right + 65} {y + 65}, {right} {y + 10}')
    if target_x > x:
        x += width
        middle = (x + target_x) / 2
        return (f'M {x} {y} C {middle} {y}, '
                f'{middle} {target_y}, {target_x} {target_y}')
    target_x += width
    route_y = min(y, target_y) - NODE_HEIGHT - ROW_GAP / 2
    return (f'M {x} {y} C {x - 45} {y}, {x - 45} {route_y}, '
            f'{x} {route_y} L {target_x} {route_y} '
            f'C {target_x + 45} {route_y}, '
            f'{target_x + 45} {target_y}, {target_x} {target_y}')


def draw_edges(svg, graph, positions, width):
    for name, dependencies in graph.items():
        for dependency in dependencies or []:
            edge = svg_element(svg, 'path', {
                'd': edge_path(positions[name], positions[dependency], width),
                'fill': 'none', 'stroke': '#64748b', 'stroke-width': '1.5',
                'marker-end': 'url(#arrow)',
                'data-source': name, 'data-target': dependency,
            })
            svg_element(edge, 'title', text=f'{name} → {dependency}')


def draw_nodes(svg, graph, positions, width):
    for name, (x, y) in positions.items():
        group = svg_element(svg, 'g', {'data-package': name})
        attributes = {
            'x': str(x), 'y': str(y), 'width': str(width),
            'height': str(NODE_HEIGHT), 'rx': '8',
            'fill': '#eff6ff', 'stroke': '#2563eb',
        }
        if graph[name] is None:
            attributes['stroke-dasharray'] = '5 5'
        svg_element(group, 'rect', attributes)
        svg_element(group, 'text', {
            'x': str(x + width / 2), 'y': str(y + NODE_HEIGHT / 2 + 5),
            'text-anchor': 'middle', 'font-family': 'sans-serif',
            'font-size': '15', 'fill': '#0f172a',
        }, name)
        status = 'Граница глубины' if graph[name] is None else name
        svg_element(group, 'title', text=status)


def svg_text(graph):
    positions, width, canvas_width, canvas_height = layout_graph(graph)
    svg = elementtree.Element('svg', {
        'xmlns': SVG_NAMESPACE, 'width': str(canvas_width),
        'height': str(canvas_height),
        'viewBox': f'0 0 {canvas_width} {canvas_height}',
        'role': 'img', 'aria-label': 'Граф зависимостей',
    })
    svg_element(svg, 'title', text='Граф зависимостей')
    svg_element(svg, 'desc', text=(
        'Стрелка: пакет → его зависимость. '
        'Пунктир: зависимости узла не раскрыты из-за глубины.'
    ))
    defs = svg_element(svg, 'defs')
    marker = svg_element(defs, 'marker', {
        'id': 'arrow', 'viewBox': '0 0 10 10', 'refX': '10', 'refY': '5',
        'markerWidth': '7', 'markerHeight': '7', 'orient': 'auto',
    })
    svg_element(marker, 'path', {'d': 'M 0 0 L 10 5 L 0 10 z',
                               'fill': '#64748b'})
    svg_element(svg, 'rect', {'width': '100%', 'height': '100%',
                            'fill': '#ffffff'})
    draw_edges(svg, graph, positions, width)
    draw_nodes(svg, graph, positions, width)
    elementtree.indent(svg)
    return elementtree.tostring(svg, encoding='unicode') + '\n'


def save_graph(graph, output):
    source = mermaid_text(graph)
    image = svg_text(graph)
    output.with_suffix('.mmd').write_text(source, encoding='utf-8')
    output.write_text(image, encoding='utf-8')
