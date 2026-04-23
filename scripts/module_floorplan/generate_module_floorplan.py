#!/usr/bin/env python3

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "runs" / "wokwi"
DEFAULT_DEF = RUNS_DIR / "final" / "def" / "tt_um_utoss_riscv.def"
DEFAULT_NETLIST = RUNS_DIR / "final" / "nl" / "tt_um_utoss_riscv.nl.v"
DEFAULT_RESOLVED = RUNS_DIR / "resolved.json"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent

SPECIAL_GROUP_ORDER = ["physical_only", "mixed", "ungrouped", "other"]
SPECIAL_GROUP_LABELS = {
    "physical_only": "physical only",
    "mixed": "mixed",
    "ungrouped": "ungrouped",
    "other": "other",
}
PALETTE = [
    "#e4572e",
    "#4b9fea",
    "#f3a712",
    "#54b435",
    "#9d4edd",
    "#ef476f",
    "#06d6a0",
    "#118ab2",
    "#fb8500",
    "#6a994e",
]
SPECIAL_COLORS = {
    "physical_only": "#d9d9d9",
    "mixed": "#7f8c8d",
    "ungrouped": "#adb5bd",
    "other": "#ced4da",
}
PHYSICAL_ONLY_RE = re.compile(
    r"__(?:antenna|endcap|fill(?:cap)?(?:_|$)|filltie(?:_|$))"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate module-colored SVG floorplan views from DEF/netlist artifacts."
    )
    parser.add_argument("--def", dest="def_path", type=Path, default=DEFAULT_DEF)
    parser.add_argument("--netlist", type=Path, default=DEFAULT_NETLIST)
    parser.add_argument("--resolved", type=Path, default=DEFAULT_RESOLVED)
    parser.add_argument("--lef", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--depths",
        type=int,
        nargs="+",
        default=[1, 2],
        help="Hierarchy depths to render, e.g. 1 for top-level, 2 for submodules.",
    )
    parser.add_argument(
        "--render",
        choices=["cells", "tiles", "both"],
        default="both",
        help="Render exact cell rectangles, coarse tiles, or both.",
    )
    parser.add_argument(
        "--tile-size-um",
        type=float,
        default=16.8,
        help="Tile size for coarse density view in microns.",
    )
    parser.add_argument(
        "--top-groups",
        type=int,
        default=8,
        help="Keep this many non-special groups, fold the rest into 'other'.",
    )
    return parser.parse_args()


def load_default_lef_path(resolved_path: Path):
    resolved = json.loads(resolved_path.read_text())
    lefs = resolved.get("CELL_LEFS") or []
    if not lefs:
        raise RuntimeError(f"Could not find CELL_LEFS in {resolved_path}")
    return Path(lefs[0])


def parse_diearea(def_text: str):
    match = re.search(
        r"DIEAREA\s+\(\s*(\d+)\s+(\d+)\s*\)\s+\(\s*(\d+)\s+(\d+)\s*\)\s*;",
        def_text,
    )
    if not match:
        raise RuntimeError("Could not find DIEAREA in DEF")
    return tuple(int(v) for v in match.groups())


def parse_components(def_text: str):
    match = re.search(r"COMPONENTS\s+\d+\s*;(.*?)END COMPONENTS", def_text, re.S)
    if not match:
        raise RuntimeError("Could not find COMPONENTS section in DEF")

    components = {}
    pattern = re.compile(
        r"-\s+(\S+)\s+(\S+)\s+\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)\s*;"
    )
    for line in match.group(1).splitlines():
        comp_match = pattern.search(line)
        if not comp_match:
            continue
        name, master, x, y, orient = comp_match.groups()
        components[name] = {
            "name": name,
            "master": master,
            "x": int(x),
            "y": int(y),
            "orient": orient,
        }
    return components


def parse_lef_sizes(lef_text: str):
    sizes = {}
    current_macro = None
    for raw_line in lef_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("MACRO "):
            current_macro = line.split()[1]
            continue
        if current_macro and line.startswith("SIZE "):
            match = re.search(r"SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;", line)
            if match:
                sizes[current_macro] = (float(match.group(1)), float(match.group(2)))
            continue
        if current_macro and line == f"END {current_macro}":
            current_macro = None
    return sizes


def iter_cell_entries(netlist_text: str):
    buffer = []
    in_cell = False
    for raw_line in netlist_text.splitlines():
        stripped = raw_line.strip()
        if not in_cell:
            if not stripped or stripped.startswith("//"):
                continue
            head = re.match(r"^\s*(\S+)\s+(\S+)\s*\(", raw_line)
            if not head:
                continue
            cell_type = head.group(1)
            if "__" not in cell_type:
                continue
            in_cell = True
            buffer = [raw_line]
            if ");" in raw_line:
                yield " ".join(buffer)
                in_cell = False
                buffer = []
            continue

        buffer.append(raw_line)
        if ");" in raw_line:
            yield " ".join(buffer)
            in_cell = False
            buffer = []


def normalize_expr(expr: str):
    expr = expr.strip()
    if not expr:
        return None
    if expr.startswith("{") or expr.startswith("'") or expr[0].isdigit():
        return None
    if expr.startswith("\\"):
        expr = expr[1:]
    return expr.strip()


def group_from_net(net_name: str, depth: int):
    if not net_name or "." not in net_name:
        return None
    first = net_name.split(".", 1)[0]
    if first.startswith("_") or first.startswith("net"):
        return None
    parts = net_name.split(".")
    if len(parts) == 1 or depth <= 1:
        return parts[0]

    # The last segment is usually the signal name, not another instance.
    # Only keep deeper grouping when the path has enough segments to prove
    # hierarchy survived flattening, e.g. core.fetch.pc_cur -> core.fetch.
    module_depth = min(depth, len(parts) - 1)
    if module_depth <= 1:
        return parts[0]
    return ".".join(parts[:module_depth])


def is_physical_only_master(master: str):
    return bool(PHYSICAL_ONLY_RE.search(master))


def classify_instance(connected_nets, master: str, depth: int):
    groups = Counter()
    for net_name in connected_nets:
        group = group_from_net(net_name, depth=depth)
        if group:
            groups[group] += 1

    if not groups:
        return "physical_only" if is_physical_only_master(master) else "ungrouped"
    if len(groups) == 1:
        return next(iter(groups))

    most_common = groups.most_common(2)
    top_group, top_count = most_common[0]
    next_group, next_count = most_common[1]
    if top_count > next_count:
        return top_group
    return "mixed"


def parse_netlist_cells(netlist_text: str, depths):
    cells = {}
    cell_pattern = re.compile(r"^\s*(\S+)\s+(\S+)\s*\(")
    pin_pattern = re.compile(r"\.\s*([A-Za-z0-9_]+)\s*\(\s*(.*?)\s*\)")

    for entry in iter_cell_entries(netlist_text):
        head = cell_pattern.match(entry)
        if not head:
            continue
        master, instance = head.groups()
        connected_nets = []
        for _pin, expr in pin_pattern.findall(entry):
            net_name = normalize_expr(expr)
            if net_name:
                connected_nets.append(net_name)
        cells[instance] = {
            "master": master,
            "nets": connected_nets,
            "seed_assignments": {
                depth: classify_instance(
                    connected_nets=connected_nets,
                    master=master,
                    depth=depth,
                )
                for depth in depths
            },
        }
    return cells


def propagate_assignments(cell_info, depth, rounds=8, max_net_degree=24):
    assignments = {
        instance: info["seed_assignments"][depth] for instance, info in cell_info.items()
    }
    net_to_instances = defaultdict(list)
    for instance, info in cell_info.items():
        for net_name in set(info["nets"]):
            net_to_instances[net_name].append(instance)

    for _ in range(rounds):
        updates = {}
        for instance, info in cell_info.items():
            current = assignments.get(instance, "ungrouped")
            if current not in {"ungrouped", "mixed"}:
                continue
            if is_physical_only_master(info["master"]):
                continue

            neighbor_groups = Counter()
            for net_name in set(info["nets"]):
                members = net_to_instances[net_name]
                if len(members) <= 1 or len(members) > max_net_degree:
                    continue
                for other in members:
                    if other == instance:
                        continue
                    other_group = assignments.get(other, "ungrouped")
                    if other_group in SPECIAL_GROUP_ORDER:
                        continue
                    neighbor_groups[other_group] += 1

            if not neighbor_groups:
                continue
            common = neighbor_groups.most_common(2)
            top_group, top_count = common[0]
            next_count = common[1][1] if len(common) > 1 else 0
            if top_count > next_count:
                updates[instance] = top_group

        if not updates:
            break
        assignments.update(updates)

    return assignments


def make_color_map(group_names):
    colors = {}
    palette_iter = iter(PALETTE)
    for group in group_names:
        if group in SPECIAL_COLORS:
            colors[group] = SPECIAL_COLORS[group]
            continue
        colors[group] = next(palette_iter, "#444444")
    return colors


def group_label(group_name: str):
    return SPECIAL_GROUP_LABELS.get(group_name, group_name)


def collapse_groups(instances, assignments, top_groups):
    group_areas = Counter()
    for inst in instances:
        group_areas[assignments.get(inst["name"], "ungrouped")] += inst["area_um2"]

    ranked = [
        group
        for group, _area in group_areas.most_common()
        if group not in SPECIAL_GROUP_ORDER
    ]
    keep = set(ranked[:top_groups])

    collapsed = {}
    for inst in instances:
        group = assignments.get(inst["name"], "ungrouped")
        if group in SPECIAL_GROUP_ORDER or group in keep:
            collapsed[inst["name"]] = group
        else:
            collapsed[inst["name"]] = "other"
    return collapsed


def build_instances(components, lef_sizes):
    instances = []
    missing_masters = Counter()
    for comp in components.values():
        size = lef_sizes.get(comp["master"])
        if not size:
            missing_masters[comp["master"]] += 1
            continue
        width_um, height_um = size
        instance = dict(comp)
        instance["width_um"] = width_um
        instance["height_um"] = height_um
        instance["width_db"] = int(round(width_um * 2000))
        instance["height_db"] = int(round(height_um * 2000))
        instance["area_um2"] = width_um * height_um
        instances.append(instance)
    return instances, missing_masters


def group_stats(instances, assignments):
    stats = defaultdict(lambda: {"cells": 0, "area_um2": 0.0, "sum_x": 0.0, "sum_y": 0.0})
    for inst in instances:
        group = assignments.get(inst["name"], "ungrouped")
        stat = stats[group]
        stat["cells"] += 1
        stat["area_um2"] += inst["area_um2"]
        cx = inst["x"] / 2000.0 + inst["width_um"] / 2.0
        cy = inst["y"] / 2000.0 + inst["height_um"] / 2.0
        stat["sum_x"] += cx * inst["area_um2"]
        stat["sum_y"] += cy * inst["area_um2"]
    for group, stat in stats.items():
        if stat["area_um2"] > 0:
            stat["cx_um"] = stat["sum_x"] / stat["area_um2"]
            stat["cy_um"] = stat["sum_y"] / stat["area_um2"]
        else:
            stat["cx_um"] = 0.0
            stat["cy_um"] = 0.0
        del stat["sum_x"]
        del stat["sum_y"]
    return dict(stats)


def render_cells_svg(path, diearea_db, instances, assignments, stats, colors, title):
    llx, lly, urx, ury = diearea_db
    die_w_um = (urx - llx) / 2000.0
    die_h_um = (ury - lly) / 2000.0
    width = 1220
    legend_w = 260
    header_h = 40
    height = max(320, int(width * die_h_um / max(die_w_um, 1.0)))
    scale_x = width / max(die_w_um, 1.0)
    scale_y = height / max(die_h_um, 1.0)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width + legend_w}" height="{height + header_h + 10}" viewBox="0 0 {width + legend_w} {height + header_h + 10}">',
        '<rect width="100%" height="100%" fill="#fbfbfc"/>',
        f'<text x="12" y="24" font-family="Helvetica" font-size="18" font-weight="bold">{title}</text>',
        f'<rect x="0" y="{header_h}" width="{width}" height="{height}" fill="#ffffff" stroke="#222" stroke-width="1"/>',
    ]

    for inst in instances:
        group = assignments.get(inst["name"], "ungrouped")
        x = (inst["x"] - llx) / 2000.0 * scale_x
        y = header_h + height - (((inst["y"] - lly) / 2000.0) + inst["height_um"]) * scale_y
        w = max(0.5, inst["width_um"] * scale_x)
        h = max(0.5, inst["height_um"] * scale_y)
        opacity = 0.85 if group not in {"physical_only", "other"} else 0.45
        lines.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="{colors[group]}" fill-opacity="{opacity:.3f}" stroke="none"/>'
        )

    label_candidates = [
        (group, stat)
        for group, stat in sorted(stats.items(), key=lambda item: -item[1]["area_um2"])
        if group not in {"physical_only", "other", "ungrouped", "mixed"}
    ][:6]
    for group, stat in label_candidates:
        x = stat["cx_um"] * scale_x
        y = header_h + height - stat["cy_um"] * scale_y
        lines.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="Helvetica" font-size="14" '
            f'fill="#111" text-anchor="middle">{group_label(group)}</text>'
        )

    legend_x = width + 18
    legend_y = 26
    lines.append(
        f'<text x="{legend_x}" y="{legend_y}" font-family="Helvetica" font-size="16" font-weight="bold">Groups</text>'
    )
    for idx, (group, stat) in enumerate(
        sorted(stats.items(), key=lambda item: (-item[1]["area_um2"], item[0]))
    ):
        y = legend_y + 22 + idx * 20
        pct = 100.0 * stat["area_um2"] / sum(s["area_um2"] for s in stats.values())
        lines.append(
            f'<rect x="{legend_x}" y="{y - 10}" width="12" height="12" fill="{colors[group]}" stroke="#444" stroke-width="0.5"/>'
        )
        lines.append(
            f'<text x="{legend_x + 18}" y="{y}" font-family="Helvetica" font-size="12">'
            f'{group_label(group)}  {stat["cells"]} cells  {pct:.1f}% area</text>'
        )

    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n")


def render_tiles_svg(path, diearea_db, instances, assignments, stats, colors, title, tile_size_um):
    llx, lly, urx, ury = diearea_db
    die_w_um = (urx - llx) / 2000.0
    die_h_um = (ury - lly) / 2000.0
    width = 1220
    legend_w = 260
    header_h = 40
    height = max(320, int(width * die_h_um / max(die_w_um, 1.0)))
    scale_x = width / max(die_w_um, 1.0)
    scale_y = height / max(die_h_um, 1.0)

    tile_map = defaultdict(Counter)
    for inst in instances:
        group = assignments.get(inst["name"], "ungrouped")
        x0 = inst["x"] / 2000.0
        y0 = inst["y"] / 2000.0
        x1 = x0 + inst["width_um"]
        y1 = y0 + inst["height_um"]
        tx0 = int(math.floor(x0 / tile_size_um))
        ty0 = int(math.floor(y0 / tile_size_um))
        tx1 = int(math.floor(max(x1 - 1e-6, x0) / tile_size_um))
        ty1 = int(math.floor(max(y1 - 1e-6, y0) / tile_size_um))
        for tx in range(tx0, tx1 + 1):
            tile_x0 = tx * tile_size_um
            tile_x1 = tile_x0 + tile_size_um
            overlap_x = max(0.0, min(x1, tile_x1) - max(x0, tile_x0))
            if overlap_x == 0.0:
                continue
            for ty in range(ty0, ty1 + 1):
                tile_y0 = ty * tile_size_um
                tile_y1 = tile_y0 + tile_size_um
                overlap_y = max(0.0, min(y1, tile_y1) - max(y0, tile_y0))
                if overlap_y == 0.0:
                    continue
                tile_map[(tx, ty)][group] += overlap_x * overlap_y

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width + legend_w}" height="{height + header_h + 10}" viewBox="0 0 {width + legend_w} {height + header_h + 10}">',
        '<rect width="100%" height="100%" fill="#fbfbfc"/>',
        f'<text x="12" y="24" font-family="Helvetica" font-size="18" font-weight="bold">{title}</text>',
        f'<rect x="0" y="{header_h}" width="{width}" height="{height}" fill="#ffffff" stroke="#222" stroke-width="1"/>',
    ]

    for (tx, ty), counter in sorted(tile_map.items()):
        total = sum(counter.values())
        if total == 0.0:
            continue
        group, dominant = counter.most_common(1)[0]
        fraction = dominant / total
        x = tx * tile_size_um * scale_x
        y = header_h + height - (ty * tile_size_um + tile_size_um) * scale_y
        w = max(1.0, tile_size_um * scale_x)
        h = max(1.0, tile_size_um * scale_y)
        opacity = 0.18 + 0.72 * fraction
        lines.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="{colors[group]}" fill-opacity="{opacity:.3f}" stroke="#ffffff" stroke-width="0.12"/>'
        )

    legend_x = width + 18
    legend_y = 26
    lines.append(
        f'<text x="{legend_x}" y="{legend_y}" font-family="Helvetica" font-size="16" font-weight="bold">Groups</text>'
    )
    for idx, (group, stat) in enumerate(
        sorted(stats.items(), key=lambda item: (-item[1]["area_um2"], item[0]))
    ):
        y = legend_y + 22 + idx * 20
        pct = 100.0 * stat["area_um2"] / sum(s["area_um2"] for s in stats.values())
        lines.append(
            f'<rect x="{legend_x}" y="{y - 10}" width="12" height="12" fill="{colors[group]}" stroke="#444" stroke-width="0.5"/>'
        )
        lines.append(
            f'<text x="{legend_x + 18}" y="{y}" font-family="Helvetica" font-size="12">'
            f'{group_label(group)}  {pct:.1f}% area</text>'
        )

    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n")


def write_summary(path, def_path, netlist_path, lef_path, summary_rows, missing_masters):
    lines = [
        "# Module Floorplan Summary",
        "",
        f"- DEF: `{def_path}`",
        f"- Netlist: `{netlist_path}`",
        f"- LEF: `{lef_path}`",
        "",
    ]
    if missing_masters:
        lines.append("## Missing LEF Sizes")
        lines.append("")
        for master, count in missing_masters.most_common():
            lines.append(f"- `{master}`: {count} instances skipped")
        lines.append("")

    for depth, rows in summary_rows.items():
        lines.append(f"## Depth {depth}")
        lines.append("")
        lines.append("| Group | Cells | Area (um^2) | Area % |")
        lines.append("| --- | ---: | ---: | ---: |")
        total_area = sum(row["area_um2"] for row in rows)
        for row in rows:
            pct = 100.0 * row["area_um2"] / total_area if total_area else 0.0
            lines.append(
                f"| `{group_label(row['group'])}` | {row['cells']} | {row['area_um2']:.2f} | {pct:.2f} |"
            )
        lines.append("")

    path.write_text("\n".join(lines) + "\n")


def main():
    args = parse_args()
    def_path = args.def_path
    netlist_path = args.netlist
    lef_path = args.lef or load_default_lef_path(args.resolved)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    def_text = def_path.read_text()
    netlist_text = netlist_path.read_text()
    lef_text = lef_path.read_text()

    diearea_db = parse_diearea(def_text)
    components = parse_components(def_text)
    lef_sizes = parse_lef_sizes(lef_text)
    instances, missing_masters = build_instances(components, lef_sizes)
    cell_info = parse_netlist_cells(netlist_text, args.depths)

    summary_rows = {}
    for depth in args.depths:
        propagated = propagate_assignments(cell_info=cell_info, depth=depth)
        collapsed = collapse_groups(
            instances=instances,
            assignments=propagated,
            top_groups=args.top_groups,
        )
        stats = group_stats(instances, collapsed)
        group_names = [
            group
            for group, _ in sorted(stats.items(), key=lambda item: (-item[1]["area_um2"], item[0]))
        ]
        colors = make_color_map(group_names)

        rows = []
        for group, stat in sorted(stats.items(), key=lambda item: (-item[1]["area_um2"], item[0])):
            rows.append({"group": group, "cells": stat["cells"], "area_um2": stat["area_um2"]})
        summary_rows[depth] = rows

        if args.render in {"cells", "both"}:
            render_cells_svg(
                path=out_dir / f"module_floorplan_depth{depth}_cells.svg",
                diearea_db=diearea_db,
                instances=instances,
                assignments=collapsed,
                stats=stats,
                colors=colors,
                title=f"Module floorplan by hierarchy depth {depth} (exact cells)",
            )
        if args.render in {"tiles", "both"}:
            render_tiles_svg(
                path=out_dir / f"module_floorplan_depth{depth}_tiles.svg",
                diearea_db=diearea_db,
                instances=instances,
                assignments=collapsed,
                stats=stats,
                colors=colors,
                title=f"Module floorplan by hierarchy depth {depth} (tile view)",
                tile_size_um=args.tile_size_um,
            )

    write_summary(
        path=out_dir / "summary.md",
        def_path=def_path,
        netlist_path=netlist_path,
        lef_path=lef_path,
        summary_rows=summary_rows,
        missing_masters=missing_masters,
    )
    (out_dir / "summary.json").write_text(json.dumps(summary_rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
