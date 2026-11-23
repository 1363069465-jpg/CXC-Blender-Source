"""Manual update checks. Worker threads never access Blender data."""
import datetime
import json
import queue
import re
import threading
import tomllib
import urllib.request
from pathlib import Path

import bpy

URL = 'https://1363069465-jpg.github.io/CXC-Blender-Source/index.json'
PACKAGE_ID = 'product_visibility_manager'
CURRENT_VERSION = tomllib.loads(Path(__file__).with_name('blender_manifest.toml').read_text(encoding='utf-8'))['version']
_state = {'busy': False, 'message': '点击检查更新，查询可用版本', 'available': ''}
_results = None


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('更新源中的版本号格式不正确')
    return tuple(map(int, value.split('.')))


def evaluate(payload, current, blender_version):
    if not isinstance(payload, dict) or payload.get('version') != 'v1' or not isinstance(payload.get('data'), list):
        raise ValueError('更新源格式不正确')
    entries = [item for item in payload['data'] if isinstance(item, dict) and item.get('id') == PACKAGE_ID]
    if not entries:
        raise ValueError('更新源中未找到显隐管理')
    compatible = []
    for item in entries:
        key = version_key(item.get('version'))
        minimum = version_key(item.get('blender_version_min', '0.0.0'))
        maximum = item.get('blender_version_max')
        if blender_version >= minimum and (not maximum or blender_version < version_key(maximum)):
            compatible.append((key, item['version']))
    if not compatible:
        return '更新源暂无适用于当前 Blender 的版本', ''
    latest_key, latest = max(compatible)
    if latest_key > version_key(current):
        return '发现可更新版本：' + latest, latest
    if latest_key < version_key(current):
        return '当前版本较新，更新源版本为 ' + latest, ''
    return '当前已是最新版本：' + current, ''


def _fetch(output, current, blender_version):
    try:
        request = urllib.request.Request(URL, headers={'User-Agent': 'CXC-Visibility-Manager', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('更新源文件过大')
        message, available = evaluate(json.loads(raw.decode('utf-8')), current, blender_version)
        output.put((message, available, True))
    except Exception as exc:
        output.put(('检查失败：' + str(exc)[:180], '', False))


def _poll():
    if _results is None:
        return None
    try:
        message, available, success = _results.get_nowait()
    except queue.Empty:
        return 0.2
    _state.update(busy=False, message=message, available=available)
    addon = bpy.context.preferences.addons.get(__package__)
    if addon:
        addon.preferences.last_update_check = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'PREFERENCES':
                area.tag_redraw()
    return None


class PVM_OT_check_release(bpy.types.Operator):
    bl_idname = 'pvm.check_release'
    bl_label = '检查更新'
    bl_description = '联网查询显隐管理可用版本，不自动安装'

    @classmethod
    def poll(cls, context):
        return not _state['busy']

    def execute(self, context):
        global _results
        if not bpy.app.online_access:
            _state.update(message='检查失败：请先在偏好设置中允许在线访问', available='')
            self.report({'WARNING'}, _state['message'])
            return {'CANCELLED'}
        _results = queue.Queue()
        _state.update(busy=True, message='正在检查更新…', available='')
        threading.Thread(target=_fetch, args=(_results, CURRENT_VERSION, tuple(bpy.app.version)), daemon=True).start()
        bpy.app.timers.register(_poll, first_interval=0.2)
        return {'FINISHED'}


class PVM_OT_open_extensions(bpy.types.Operator):
    bl_idname = 'pvm.open_extensions'
    bl_label = '前往扩展管理更新'
    bl_description = '在获取扩展中刷新仓库，然后更新显隐管理'

    def execute(self, context):
        context.preferences.active_section = 'EXTENSIONS'
        return {'FINISHED'}


def draw(layout, preferences):
    box = layout.box()
    box.label(text='插件更新', icon='FILE_REFRESH')
    box.label(text='当前版本：' + CURRENT_VERSION)
    row = box.row()
    row.label(text='上次检查时间：' + preferences.last_update_check)
    row.operator('pvm.check_release', text='检查中…' if _state['busy'] else '检查更新')
    box.label(text=_state['message'], icon='ERROR' if _state['message'].startswith('检查失败') else 'INFO')
    if _state['available']:
        box.label(text=CURRENT_VERSION + ' → ' + _state['available'])
        box.operator('pvm.open_extensions', icon='IMPORT')
        box.label(text='在获取扩展中刷新仓库后，更新显隐管理。')


CLASSES = (PVM_OT_check_release, PVM_OT_open_extensions)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    global _results
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
    _results = None
    _state.update(busy=False, available='', message='点击检查更新，查询可用版本')
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
