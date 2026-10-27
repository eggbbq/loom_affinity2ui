# Ported from the verified psd2ui snapshot; provenance: vendor/prefab-origin.json.
"""Compile layout.json to editable LayaAir 3.4.1 .lh assets, without runtime UI code."""
import hashlib
import json
import math
import shutil
import uuid
from pathlib import Path, PurePosixPath

from PIL import Image

from .naming import inside
from .laya_types import component_layout, new_ui_component
from .layout_helpers import layout_gap, ordered_children


def write_json(path, data):
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def meta_for(path, project, texture=False):
    meta = inside(project, path.with_suffix(path.suffix + ".meta").relative_to(project).as_posix())
    if meta.exists():
        data = json.loads(meta.read_text(encoding="utf-8"))
        uuid.UUID(data["uuid"])
    else:
        data = {"uuid": str(uuid.uuid5(uuid.NAMESPACE_URL,
                       "psd2ui:laya:" + path.relative_to(project).as_posix()))}
        if texture:
            data["importer"] = {"textureType": 2, "sRGB": True,
                                "generateMipmap": False, "npot": 0, "maxSize": 0,
                                "usePng8": False}
    return meta, data


def node_id(path):
    return "psd" + hashlib.sha256("/".join(map(str, path)).encode()).hexdigest()[:13]


def validate_layout(node, root=True):
    if not isinstance(node, dict) or node.get("type") not in (("root",) if root else ("container", "image", "text")):
        raise ValueError("Invalid layout node type")
    if root and node.get("version") != 1:
        raise ValueError("Only layout version 1 is supported")
    if not isinstance(node.get("name"), str) or not isinstance(node.get("visible"), bool):
        raise ValueError("Missing node name/visible")
    for key in ("position", "size"):
        values = node.get(key)
        if (not isinstance(values, list) or len(values) != 2 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)):
            raise ValueError(f"Invalid {key}: {node['name']}")
    if min(node["size"]) < 0:
        raise ValueError(f"Negative size: {node['name']}")
    if "opacity" in node and (isinstance(node["opacity"], bool) or
            not isinstance(node["opacity"], (int, float)) or not 0 <= node["opacity"] <= 1):
        raise ValueError(f"Invalid opacity: {node['name']}")
    if "component" in node:
        component = new_ui_component(node["component"])
        if (not component or node["type"] == "root" or
                node["type"] == "image" and component not in ("GImage", "GLoader") or
                node["type"] == "text" and component not in ("GTextField", "GTextInput")):
            raise ValueError(f"Invalid New UI component: {node['name']}")
    if "layout" in node and (node["type"] != "container" or
            new_ui_component(node.get("component", "GBox")) not in ("GBox", "GPanel", "GList", "GTree") or
            node["layout"] not in ("horizontal", "vertical")):
        raise ValueError(f"Invalid container layout: {node['name']}")
    if "gap" in node and ("layout" not in node or isinstance(node["gap"], bool) or
            not isinstance(node["gap"], (int, float)) or not math.isfinite(node["gap"])):
        raise ValueError(f"Invalid layout gap: {node['name']}")
    if node["type"] in ("root", "container"):
        if not isinstance(node.get("children"), list):
            raise ValueError(f"Missing children: {node['name']}")
        for child in node["children"]:
            validate_layout(child, root=False)
    elif node["type"] == "image":
        asset = node.get("asset")
        if (not isinstance(asset, str) or not asset or "\\" in asset or ":" in asset or
                asset.startswith("/") or any(part in ("", ".", "..") for part in asset.split("/")) or
                PurePosixPath(asset).suffix.lower() != ".png"):
            raise ValueError(f"Unsafe PNG asset path: {asset}")
    elif node["type"] == "text":
        if not isinstance(node.get("text"), str) or node.get("align", "left") not in ("left", "center", "right"):
            raise ValueError(f"Invalid text/alignment: {node['name']}")
        for key in ("fontSize", "outline", "shadowBlur"):
            if key in node and (isinstance(node[key], bool) or not isinstance(node[key], (int, float)) or
                                not math.isfinite(node[key]) or node[key] < 0):
                raise ValueError(f"Invalid text {key}: {node['name']}")
        if "shadow" in node:
            shadow = node["shadow"]
            if (not isinstance(shadow, list) or len(shadow) != 2 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in shadow)):
                raise ValueError(f"Invalid text shadow: {node['name']}")
        for key in ("font", "color", "outlineColor", "shadowColor"):
            if key in node and not isinstance(node[key], str):
                raise ValueError(f"Invalid text {key}: {node['name']}")


def bundle_name(layout):
    name = layout["name"]
    if not name or name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise ValueError(f"Invalid PSD bundle name: {name}")
    return name


def generate_prefab(layout_path, project, output=None, scene=None, *,
                    preserve_resource_paths=False, scene_instance_id=None):
    if output is None:
        layout = json.loads(Path(layout_path).read_text(encoding="utf-8"))
        validate_layout(layout)
        output = f"assets/PSD2UI/{bundle_name(layout)}.lh"
    return _generate_prefab(layout_path, project, output, scene,
                            preserve_resource_paths=preserve_resource_paths,
                            scene_instance_id=scene_instance_id)




def _generate_prefab(layout_path, project, output, scene, *, assets_root=None, texture_root=None,
                     preserve_resource_paths=False, scene_instance_id=None):
    layout_path = Path(layout_path).resolve()
    project = Path(project).resolve()
    if not project.is_dir():
        raise ValueError(f"Project does not exist: {project}")
    destination = inside(project, str(output))
    if preserve_resource_paths and texture_root is None:
        texture_root = destination.parent
    assets_root = (Path(assets_root) if assets_root is not None else project / "assets").resolve()
    if not destination.is_relative_to(assets_root) or destination.suffix != ".lh":
        raise ValueError("Prefab output must be a .lh inside the project's assets directory")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    validate_layout(layout)
    source = layout_path.parent
    textures = {}
    sizes = {}
    counts = {"nodes": 0, "images": 0, "texts": 0, "containers": 0}
    def collect(node):
        if node["type"] == "image":
            asset = node["asset"]
            path = inside(source, asset)
            if asset not in sizes:
                with Image.open(path) as image:
                    if image.format != "PNG":
                        raise ValueError(f"Asset is not a PNG: {asset}")
                    sizes[asset] = list(image.size)
            if sizes[asset] != node["size"]:
                raise ValueError(f"PNG/node size mismatch: {asset}: {sizes[asset]} != {node['size']}")
            target = inside(Path(texture_root) if texture_root is not None else destination.with_suffix(""), asset)
            if not target.is_relative_to(assets_root):
                raise ValueError(f"Texture destination escapes project assets: {asset}")
            meta, data = meta_for(target, project, texture=True)
            textures[asset] = (path, target, meta, data)
        for child in node.get("children", []):
            collect(child)
    collect(layout)

    prefab_meta, prefab_data = meta_for(destination, project)
    scene_path, scene_data = None, None
    instance_id = scene_instance_id or node_id(("instance", destination.relative_to(project).as_posix()))
    if scene is not None:
        scene_path = inside(project, str(scene))
        if not scene_path.is_relative_to(assets_root) or scene_path.suffix != ".ls":
            raise ValueError("Startup scene must be a .ls inside assets")
        scene_data = json.loads(scene_path.read_text(encoding="utf-8"))
        if scene_data.get("_$type") != "Scene":
            raise ValueError("Startup file is not a Laya Scene")
        children = scene_data.setdefault("_$child", [])
        if not isinstance(children, list):
            raise ValueError("Invalid scene children")
        instance = next((n for n in children if n.get("_$id") == instance_id), None)
        if instance is None:
            children.append({"_$id": instance_id, "_$prefab": prefab_data["uuid"]})
        else:
            # Preserve the user's scene instance overrides and additional nodes.
            instance["_$prefab"] = prefab_data["uuid"]
        # Remove only this demo's old dynamic loader component, preserving others.
        main_meta = project / "src/Main.ts.meta"
        main_uuid = json.loads(main_meta.read_text(encoding="utf-8"))["uuid"] if main_meta.exists() else None
        components = scene_data.get("_$comp", [])
        scene_data["_$comp"] = [c for c in components if c.get("_$type") not in (main_uuid, "Main")]
        if not scene_data["_$comp"]:
            scene_data.pop("_$comp")
        scene_data.update(width=layout["size"][0], height=layout["size"][1])

    def convert(node, path=()):
        counts["nodes"] += 1
        kind = node["type"]
        node_type = new_ui_component(node.get("component")) or {
            "root": "GWidget", "container": "GWidget", "text": "GTextField", "image": "GImage"}[kind]
        result = {"_$id": node_id(path), "_$type": node_type,
                  "name": node["name"], "x": node["position"][0], "y": node["position"][1],
                  "width": node["size"][0], "height": node["size"][1],
                  "visible": node["visible"]}
        layout = node.get("layout") or component_layout(node.get("component"))
        if layout:
            gap = node.get("gap", layout_gap(node["children"], layout)[0])
            result["layout"] = {"type": 2 if layout == "horizontal" else 1,
                                "columnGap" if layout == "horizontal" else "rowGap": gap}
        if kind in ("container", "text") and "opacity" in node:
            result["alpha"] = node["opacity"]
        if kind == "image":
            counts["images"] += 1
            texture_uuid = textures[node["asset"]][3]["uuid"]
            if node_type == "GLoader":
                result["src"] = "res://" + texture_uuid
                result["fitMode"] = 1  # LoaderFitMode.Fill; retain explicit layout size.
            else:
                result["src"] = "res://" + texture_uuid
                result["autoSize"] = False
        elif kind == "text":
            counts["texts"] += 1
            result.update(text=node["text"], align=node.get("align", "left"), valign="top",
                          padding=[0, 0, 0, 0], stroke=node.get("outline", 0))
            if node_type == "GTextInput":
                result["multiline"] = "\n" in node["text"]
            else:
                result.update(wordWrap=False, overflow="visible")
            styles = [("font", "font"), ("fontSize", "fontSize"), ("color", "color"),
                      ("outlineColor", "strokeColor")]
            if node_type != "GTextInput":
                styles.extend((("shadowColor", "shadowColor"), ("shadowBlur", "shadowBlur")))
            for key, target in styles:
                if key in node:
                    result[target] = node[key]
            if "shadow" in node and node_type != "GTextInput":
                result.update(shadowOffsetX=node["shadow"][0], shadowOffsetY=node["shadow"][1])
        else:
            counts["containers"] += 1
            children = ordered_children(node["children"], layout) if layout else node["children"]
            result["_$child"] = [convert(child, (*path, index)) for index, child in enumerate(children)]
        return result

    prefab = {"_$ver": 1, **convert(layout)}
    # All input/reference validation finishes before any generated resource is written.
    for path, target, meta, data in textures.values():
        target.parent.mkdir(parents=True, exist_ok=True)
        if path != target:
            shutil.copy2(path, target)
        write_json(meta, data)
    write_json(destination, prefab)
    write_json(prefab_meta, prefab_data)
    if scene_path is not None:
        write_json(scene_path, scene_data)
    return {"prefab": str(destination), "uuid": prefab_data["uuid"],
            "textures": len(textures), **counts}

