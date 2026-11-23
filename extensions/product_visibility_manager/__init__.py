import bpy
from . import updater
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup, UIList


def scope(root):
    # Single traversal: children_recursive repeatedly scans all objects.
    children = {}
    for obj in bpy.data.objects:
        if obj.parent:
            children.setdefault(obj.parent, []).append(obj)
    result, stack = [], [root]
    while stack:
        obj = stack.pop()
        result.append(obj)
        stack.extend(children.get(obj, ()))
    return result


def root_for(context):
    root = context.scene.pvm_target
    return root if root and root.name in context.scene.objects else None


def recorded_roots(scene):
    # Include hidden/excluded objects, but never unrelated scenes.
    return sorted((obj for obj in scene.objects if len(obj.pvm_data.variants)),
                  key=lambda obj: obj.name.casefold())


def active_variant(root):
    data = root.pvm_data
    return data.variants[data.index] if 0 <= data.index < len(data.variants) else None


def ensure_editable(root, objects):
    for obj in [root] + list(objects):
        if not obj.is_editable or obj.library or obj.override_library:
            raise ValueError('请先将产品追加为本地物体；本版不编辑链接或库覆盖物体')


def read_states(context, root):
    objects = scope(root)
    ensure_editable(root, objects)
    states = []
    for obj in objects:
        if obj.name not in context.view_layer.objects:
            raise ValueError('有零件被集合排除或不在当前视图层，请先恢复集合：' + obj.name)
        eye = obj.hide_get(view_layer=context.view_layer)
        states.append((obj, eye, obj.hide_viewport, obj.hide_render))
    return states


def write_states(root, variant, states):
    variant.states.clear()
    for obj, eye, viewport, render in states:
        item = variant.states.add()
        item.is_root = obj == root
        if not item.is_root:
            item.obj = obj
        item.label = obj.name
        item.eye, item.viewport, item.render = eye, viewport, render


def apply_variant(context, root, variant):
    current = set(scope(root))
    actions, skipped, recorded = [], 0, set()
    for item in variant.states:
        obj = root if item.is_root else item.obj
        if obj is None or obj not in current:
            skipped += 1
            continue
        recorded.add(obj)
        if obj.name not in context.view_layer.objects:
            skipped += 1
            continue
        actions.append((obj, item))
    ensure_editable(root, [obj for obj, _ in actions])
    # Validate before any visibility changes.
    before = [(obj, obj.hide_get(view_layer=context.view_layer), obj.hide_viewport,
               obj.hide_render) for obj, _ in actions]
    try:
        for obj, item in actions:
            obj.hide_viewport = item.viewport
            obj.hide_render = item.render
            obj.hide_set(item.eye, view_layer=context.view_layer)
    except Exception:
        for obj, eye, viewport, render in before:
            obj.hide_viewport = viewport
            obj.hide_render = render
            obj.hide_set(eye, view_layer=context.view_layer)
        raise
    context.view_layer.update()
    blocked = sum(not obj.visible_get(view_layer=context.view_layer)
                   for obj, _ in actions
                   if not obj.hide_get(view_layer=context.view_layer) and not obj.hide_viewport)

    return len(actions), skipped, len(current - recorded), blocked


class PVM_State(PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object)
    is_root: BoolProperty()
    label: StringProperty()
    eye: BoolProperty()
    viewport: BoolProperty()
    render: BoolProperty()


class PVM_Variant(PropertyGroup):
    name: StringProperty(default='新形态')
    states: CollectionProperty(type=PVM_State)


class PVM_Data(PropertyGroup):
    variants: CollectionProperty(type=PVM_Variant)
    index: IntProperty(default=0)


class PVM_OT_target(Operator):
    bl_idname = 'pvm.set_target'
    bl_label = '将选中物体设为总父级'
    bl_description = '仅指定记录范围，不修改父子关系；请选中你已有的产品总父级'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.name not in context.scene.objects:
            self.report({'ERROR'}, '请先选中产品总父级')
            return {'CANCELLED'}
        context.scene.pvm_target = obj
        return {'FINISHED'}


class PVM_OT_pick_recorded(Operator):
    bl_idname = 'pvm.pick_recorded'
    bl_label = '选用已有记录的物体'
    bl_description = '将此物体设为总父级并显示已有记录；不改变物体显隐'
    bl_options = {'REGISTER', 'UNDO'}
    object_name: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        obj = context.scene.objects.get(self.object_name)
        if obj is None or not len(obj.pvm_data.variants):
            self.report({'WARNING'}, '该物体已移除、改名或没有显隐记录，请重新选择')
            return {'CANCELLED'}
        context.scene.pvm_target = obj
        return {'FINISHED'}


class PVM_OT_record(Operator):
    bl_idname = 'pvm.record'
    bl_label = '记录当前形态'
    bl_options = {'REGISTER', 'UNDO'}
    variant_name: StringProperty(name='形态名称', default='新形态')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        root = root_for(context)
        if not root or not self.variant_name.strip():
            self.report({'ERROR'}, '请选择总父级并填写名称')
            return {'CANCELLED'}
        try:
            states = read_states(context, root)
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        variant = root.pvm_data.variants.add()
        variant.name = self.variant_name.strip()
        write_states(root, variant, states)
        root.pvm_data.index = len(root.pvm_data.variants) - 1
        self.report({'INFO'}, '已记录 %d 个物体的三项显隐状态' % len(states))
        return {'FINISHED'}


class PVM_OT_apply(Operator):
    bl_idname = 'pvm.apply'
    bl_label = '应用形态'
    bl_options = {'REGISTER', 'UNDO'}
    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def execute(self, context):
        root = root_for(context)
        if not root:
            return {'CANCELLED'}
        idx = self.index if self.index >= 0 else root.pvm_data.index
        if not 0 <= idx < len(root.pvm_data.variants):
            return {'CANCELLED'}
        try:
            count, skipped, new, blocked = apply_variant(context, root, root.pvm_data.variants[idx])
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        root.pvm_data.index = idx
        if skipped or new or blocked:
            self.report({'WARNING'}, '已应用 %d 项；失效/范围外 %d，新物体保持原状 %d，仍受集合等限制 %d' % (count, skipped, new, blocked))
        else:
            self.report({'INFO'}, '已应用：' + root.pvm_data.variants[idx].name)
        return {'FINISHED'}


class PVM_OT_update(Operator):
    bl_idname = 'pvm.update'
    bl_label = '用当前显隐覆盖记录'
    bl_description = '覆盖列表所选形态，并将新加入的子级纳入记录'
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        root = root_for(context)
        variant = active_variant(root) if root else None
        if variant is None:
            return {'CANCELLED'}
        try:
            states = read_states(context, root)
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        write_states(root, variant, states)
        self.report({'INFO'}, '已更新：' + variant.name)
        return {'FINISHED'}


class PVM_OT_delete(Operator):
    bl_idname = 'pvm.delete'
    bl_label = '删除所选形态记录'
    bl_description = '只删除显隐记录，不删除任何物体'
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        root = root_for(context)
        if root is None or active_variant(root) is None:
            return {'CANCELLED'}
        try:
            ensure_editable(root, [])
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        data = root.pvm_data
        data.variants.remove(data.index)
        data.index = max(0, min(data.index, len(data.variants) - 1))
        return {'FINISHED'}


class PVM_OT_move(Operator):
    bl_idname = 'pvm.move'
    bl_label = '移动形态'
    bl_description = '将选中的形态向上或向下移动一行'
    bl_options = {'REGISTER', 'UNDO'}
    step: IntProperty(default=-1, min=-1, max=1, options={'SKIP_SAVE'})

    def execute(self, context):
        root = root_for(context)
        if root is None:
            return {'CANCELLED'}
        try:
            ensure_editable(root, [])
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        data = root.pvm_data
        source = data.index
        target = source + self.step
        if self.step not in {-1, 1} or not (0 <= source < len(data.variants) and 0 <= target < len(data.variants)):
            return {'CANCELLED'}
        data.variants.move(source, target)
        data.index = target
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PVM_UL_variants(UIList):
    def draw_filter(self, context, layout):
        # Manual order remains authoritative; no alphabetical sort controls.
        pass

    def filter_items(self, context, data, propname):
        return [], []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, 'name', text='', emboss=False)
        row.label(text=str(len(item.states)))
        row.operator('pvm.apply', text='', icon='PLAY').index = index


class PVM_Preferences(AddonPreferences):
    bl_idname = __package__

    last_update_check: StringProperty(name="上次检查时间", default="尚未检查")

    def draw(self, context):
        layout = self.layout
        updater.draw(layout, self)
        box = layout.box()
        box.label(text='使用说明', icon='HELP')
        for line in (
            '1. 在总父级字段选择物体，或用字段内吸管拾取已有总父级。',
            '2. 手动调整零件显隐，点击列表左侧“＋”记录并命名。',
            '3. 点击形态右侧的播放三角图标，恢复该行形态的显隐。',
            '4. 修改显隐后点击左侧刷新图标，更新所选记录。',
            '5. 名称可直接修改；左侧“－”只删除所选记录，不删除模型。',
            '6. 保存 .blend；导入完整产品后重新指定原总父级。',
            '展开“父级对象”，可查看带记录的物体；点击吸管选用。',
            '7. 选中形态，点击列表左侧的上下三角按钮调整顺序。',
        ):
            box.label(text=line)
        layout.label(text='记录：物体小眼睛、显示器、相机', icon='INFO')
        layout.label(text='集合显隐与局部视图不在记录范围')
        layout.label(text='记录、更新和应用始终包含小眼睛、显示器、相机三项状态。')
        layout.label(text='渲染独立恢复相机记录，不再根据视口状态推算。')


class PVM_PT_panel(Panel):
    bl_label = '显隐管理'
    bl_idname = 'PVM_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '显隐管理'

    def draw(self, context):
        layout = self.layout
        target_row = layout.row(align=True)
        target_row.prop(context.scene, 'pvm_target', text='总父级')
        root = root_for(context)
        if not root:
            return
        data = root.pvm_data
        col = layout.column()
        col.enabled = bool(root.is_editable and not root.library and not root.override_library)
        list_row = col.row()
        controls = list_row.column(align=True)
        up = controls.column(align=True)
        up.enabled = 0 < data.index < len(data.variants)
        up.operator('pvm.move', text='', icon='TRIA_UP').step = -1
        down = controls.column(align=True)
        down.enabled = 0 <= data.index < len(data.variants) - 1
        down.operator('pvm.move', text='', icon='TRIA_DOWN').step = 1
        controls.separator()
        controls.operator('pvm.record', text='', icon='ADD')
        remove = controls.column(align=True)
        remove.enabled = active_variant(root) is not None
        remove.operator('pvm.delete', text='', icon='REMOVE')
        controls.separator()
        update = controls.column(align=True)
        update.enabled = active_variant(root) is not None
        update.operator('pvm.update', text='', icon='FILE_REFRESH')
        list_row.template_list('PVM_UL_variants', '', data, 'variants', data, 'index', rows=5)
        variant = active_variant(root)
        if variant:
            col.prop(variant, 'name', text='重命名')


class PVM_PT_parents(Panel):
    bl_label = '父级对象'
    bl_idname = 'PVM_PT_parents'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '显隐管理'

    def draw(self, context):
        layout = self.layout
        roots = recorded_roots(context.scene)
        if not roots:
            layout.label(text='当前场景没有物体显隐记录', icon='INFO')
            return
        for obj in roots:
            row = layout.row(align=True)
            row.label(text=obj.name, icon='OBJECT_DATA')
            row.label(text=str(len(obj.pvm_data.variants)) + ' 条')
            row.operator('pvm.pick_recorded', text='', icon='EYEDROPPER').object_name = obj.name


CLASSES = (PVM_State, PVM_Variant, PVM_Data, PVM_OT_target, PVM_OT_pick_recorded, PVM_OT_record,
           PVM_OT_apply, PVM_OT_update, PVM_OT_delete, PVM_OT_move, PVM_UL_variants,
           PVM_Preferences, PVM_PT_panel, PVM_PT_parents)


def register():
    # Fail before changing another add-on's properties or registering a duplicate copy.
    if hasattr(bpy.types.Object, 'pvm_data') or hasattr(bpy.types.Scene, 'pvm_target'):
        raise RuntimeError('显隐管理的同名属性已注册，请停用旧版或重复安装的插件后重启 Blender')
    updater.register()
    registered = []
    try:
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            registered.append(cls)
        bpy.types.Object.pvm_data = PointerProperty(type=PVM_Data)
        bpy.types.Scene.pvm_target = PointerProperty(type=bpy.types.Object, name='产品总父级')
    except Exception:
        if hasattr(bpy.types.Scene, 'pvm_target'):
            del bpy.types.Scene.pvm_target
        if hasattr(bpy.types.Object, 'pvm_data'):
            del bpy.types.Object.pvm_data
        for cls in reversed(registered):
            bpy.utils.unregister_class(cls)
        updater.unregister()
        raise


def unregister():
    updater.unregister()
    del bpy.types.Scene.pvm_target
    del bpy.types.Object.pvm_data
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
