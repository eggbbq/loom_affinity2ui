# Ported from the verified psd2ui snapshot; provenance: vendor/prefab-origin.json.
"""New UI widget types from official LayaAir 3.4.1 LayaAir.d.ts.

Source SHA256: 0c06535e814e5cf1f53ac65e7e2436ba12bf5590879c9ae0bb975a4d5b30623b
"""

NEW_UI_TYPES = frozenset((
    'GBox',
    'GButton',
    'GComboBox',
    'GImage',
    'GLabel',
    'GList',
    'GLoader',
    'GMovieClip',
    'GPanel',
    'GProgressBar',
    'GRoot',
    'GScrollBar',
    'GSlider',
    'GTextField',
    'GTextInput',
    'GTree',
    'GWidget',
    'GWindow',
))

# Both button_ and gbutton_ resolve to GButton, including canonical casing.
NEW_UI_NAMES = {key: name for name in NEW_UI_TYPES
                for key in (name.lower(), name[1:].lower())}
TYPE_ALIASES = {"hbox": "GBox", "vbox": "GBox", "vhox": "GBox",
                "pnl": "GPanel", "btn": "GButton", "icon": "GLoader", "ico": "GLoader",
                "txt": "GTextField", "text": "GTextField", "title": "GTextField",
                "input": "GTextInput", "img": "GImage", "bar": "GProgressBar",
                "背景": "GImage", "按钮": "GButton", "标题": "GTextField",
                "边框": "GImage", "图标": "GLoader", "图片": "GImage",
                "花边": "GImage", "底板": "GImage"}


def new_ui_component(name):
    if not isinstance(name, str):
        return None
    key = name.lower()
    return TYPE_ALIASES.get(key, NEW_UI_NAMES.get(key))


def component_layout(name):
    key = name.lower() if isinstance(name, str) else ""
    return {"hbox": "horizontal", "vbox": "vertical", "vhox": "vertical"}.get(key)
