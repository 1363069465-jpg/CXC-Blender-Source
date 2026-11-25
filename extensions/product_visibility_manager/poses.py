"""Object joint poses, stored on the selected product root."""
import bpy
import bpy.utils.previews
from pathlib import Path
from bpy.props import BoolProperty, CollectionProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList


_TOOL_ICONS = None


def tool_icon(name):
    global _TOOL_ICONS
    if _TOOL_ICONS is None:
        _TOOL_ICONS = bpy.utils.previews.new()
    if name not in _TOOL_ICONS:
        _TOOL_ICONS.load(name, str(Path(__file__).parent / 'icons' / (name + '.png')), 'IMAGE')
    return _TOOL_ICONS[name].icon_id


def unregister_icons():
    global _TOOL_ICONS
    if _TOOL_ICONS is not None:
        bpy.utils.previews.remove(_TOOL_ICONS)
        _TOOL_ICONS = None


def next_name(data, records):
    numbers = [int(item.name[2:]) for item in records
               if item.name.startswith('形态') and item.name[2:].isascii() and item.name[2:].isdigit()]
    return '形态%02d' % (max([data.name_counter] + numbers + [0]) + 1)


def advance_name(data, name):
    if name.startswith('形态') and name[2:].isascii() and name[2:].isdigit():
        data.name_counter = max(data.name_counter, int(name[2:]))


def root_for(context):
    root = context.scene.pvm_target
    return root if root and root.name in context.scene.objects else None


def belongs(obj, root):
    while obj:
        if obj == root:
            return True
        obj = obj.parent
    return False


def editable(obj):
    if not obj or not obj.is_editable or obj.library or obj.override_library:
        raise ValueError('请选择本地可编辑物体；暂不支持链接或库覆盖物体')


def active(root):
    data = root.pvm_pose_data
    return data.poses[data.index] if 0 <= data.index < len(data.poses) else None


def configured(root):
    objects = sorted(root.children_recursive, key=lambda obj: obj.name)
    if not objects:
        raise ValueError('总父级下没有子物体')
    for obj in objects:
        editable(obj)
    return objects


def snapshot(obj):
    return (obj.rotation_mode, tuple(obj.rotation_euler), tuple(obj.rotation_quaternion),
            tuple(obj.rotation_axis_angle), tuple(obj.delta_rotation_euler), tuple(obj.delta_rotation_quaternion),
            tuple(obj.location), tuple(obj.delta_location))


def restore(obj, values):
    mode, euler, quat, axis, delta_euler, delta_quat, location, delta_location = values
    obj.rotation_mode = mode
    obj.rotation_euler = euler
    obj.rotation_quaternion = quat
    obj.rotation_axis_angle = axis
    obj.delta_rotation_euler = delta_euler
    obj.delta_rotation_quaternion = delta_quat
    obj.location = location
    obj.delta_location = delta_location


def save_states(root, pose, joints):
    if not (root.pvm_pose_data.record_rotation or root.pvm_pose_data.record_location):
        raise ValueError('请至少勾选旋转或移动')
    # Read everything before replacing a saved pose.
    values = [(obj, snapshot(obj)) for obj in joints]
    pose.states.clear()
    for obj, values in values:
        item = pose.states.add()
        item.is_root = obj == root
        if not item.is_root:
            item.obj = obj
        item.label = obj.name
        # Root is allowed to move to another parent; child joints must keep their recorded parent.
        item.parent_is_root = obj.parent == root
        item.had_parent = obj.parent is not None
        if not item.is_root and not item.parent_is_root:
            item.parent_obj = obj.parent
        (item.mode, item.euler, item.quaternion, item.axis_angle,
         item.delta_euler, item.delta_quaternion, item.location, item.delta_location) = values
        item.has_rotation = root.pvm_pose_data.record_rotation
        item.has_location = root.pvm_pose_data.record_location


def resolve(root, item):
    obj = root if item.is_root else item.obj
    if not obj or not belongs(obj, root):
        return None
    if not item.is_root:
        parent = root if item.parent_is_root else item.parent_obj
        if (item.had_parent and parent is None) or obj.parent != parent:
            return None
    return obj


def apply_pose(context, root, pose):
    editable(root)
    actions = [(resolve(root, item), item) for item in pose.states]
    valid = [(obj, item) for obj, item in actions if obj and obj.name in context.scene.objects]
    if not valid:
        raise ValueError('记录中的物体已删除、移出范围或改变父级，未应用姿态')
    for obj, _ in valid:
        editable(obj)
    before = [(obj, snapshot(obj)) for obj, _ in valid]
    try:
        for obj, item in valid:
            if item.has_rotation:
                obj.rotation_mode = item.mode
                obj.rotation_euler = item.euler
                obj.rotation_quaternion = item.quaternion
                obj.rotation_axis_angle = item.axis_angle
                obj.delta_rotation_euler = item.delta_euler
                obj.delta_rotation_quaternion = item.delta_quaternion
            if item.has_location:
                obj.location = item.location
                obj.delta_location = item.delta_location
        context.view_layer.update()
    except Exception:
        for obj, values in before:
            restore(obj, values)
        context.view_layer.update()
        raise
    controlled = sum(bool(obj.constraints or obj.animation_data) for obj, _ in valid)
    return len(valid), len(actions) - len(valid), controlled


class PVM_PoseState(PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object)
    is_root: BoolProperty()
    label: StringProperty()
    parent_obj: PointerProperty(type=bpy.types.Object)
    parent_is_root: BoolProperty()
    had_parent: BoolProperty()
    has_rotation: BoolProperty(default=True)
    has_location: BoolProperty(default=False)
    location: FloatVectorProperty(size=3)
    delta_location: FloatVectorProperty(size=3)
    mode: StringProperty(default='XYZ')
    euler: FloatVectorProperty(size=3)
    quaternion: FloatVectorProperty(size=4, default=(1, 0, 0, 0))
    axis_angle: FloatVectorProperty(size=4, default=(0, 0, 1, 0))
    delta_euler: FloatVectorProperty(size=3)
    delta_quaternion: FloatVectorProperty(size=4, default=(1, 0, 0, 0))


class PVM_Pose(PropertyGroup):
    name: StringProperty(default='形态01')
    states: CollectionProperty(type=PVM_PoseState)


class PVM_PoseData(PropertyGroup):
    name_counter: IntProperty(default=0)
    record_rotation: BoolProperty(name='旋转', default=True, description='新增或刷新时记录旋转')
    record_location: BoolProperty(name='移动', default=True, description='新增或刷新时记录位置')
    poses: CollectionProperty(type=PVM_Pose)
    index: IntProperty(default=0)


class PoseOperator:
    @classmethod
    def poll(cls, context):
        root = root_for(context)
        return context.mode == 'OBJECT' and root is not None and root.is_editable and not root.library and not root.override_library


class PVM_OT_pose_record(PoseOperator, Operator):
    bl_idname = 'pvm.pose_record'
    bl_label = '记录当前姿态'
    bl_description = '自动记录总父级下全部子物体的局部位置和旋转'
    bl_options = {'REGISTER', 'UNDO'}
    pose_name: StringProperty(name='姿态名称', default='', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        root = root_for(context)
        self.pose_name = next_name(root.pvm_pose_data, root.pvm_pose_data.poses)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        root = root_for(context)
        try:
            if not (root.pvm_pose_data.record_rotation or root.pvm_pose_data.record_location):
                raise ValueError('请至少勾选旋转或移动')
            joints = configured(root)
            if any(obj.name not in context.scene.objects for obj in joints):
                raise ValueError('子物体必须在当前场景中')
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        data = root.pvm_pose_data
        name = self.pose_name.strip() or next_name(data, data.poses)
        pose = data.poses.add()
        pose.name = name
        advance_name(data, name)
        save_states(root, pose, joints)
        data.index = len(data.poses) - 1
        self.report({'INFO'}, '已记录 %d 个物体：%s' % (len(joints), pose.name))
        return {'FINISHED'}


class PVM_OT_pose_apply(PoseOperator, Operator):
    bl_idname = 'pvm.pose_apply'
    bl_label = '应用姿态'
    bl_description = '恢复子物体的位置和旋转；已移出总父级的物体会跳过'
    bl_options = {'REGISTER', 'UNDO'}
    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def execute(self, context):
        root = root_for(context)
        data = root.pvm_pose_data
        index = data.index if self.index < 0 else self.index
        if not 0 <= index < len(data.poses):
            return {'CANCELLED'}
        try:
            count, skipped, controlled = apply_pose(context, root, data.poses[index])
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        data.index = index
        self.report({'WARNING'} if skipped or controlled else {'INFO'},
                    '已恢复 %d 个物体；跳过 %d 个；有动画/约束的物体 %d 个' % (count, skipped, controlled))
        return {'FINISHED'}


class PVM_OT_pose_update(PoseOperator, Operator):
    bl_idname = 'pvm.pose_update'
    bl_label = '更新所选姿态'
    bl_description = '用总父级下当前全部子物体的位置和旋转覆盖此姿态'
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        root = root_for(context)
        pose = active(root)
        if pose is None:
            return {'CANCELLED'}
        try:
            joints = configured(root)
            if any(obj.name not in context.scene.objects for obj in joints):
                raise ValueError('子物体必须在当前场景中')
            save_states(root, pose, joints)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, '已更新：' + pose.name)
        return {'FINISHED'}


class PVM_OT_pose_delete(PoseOperator, Operator):
    bl_idname = 'pvm.pose_delete'
    bl_label = '删除所选姿态记录'
    bl_description = '只删除记录，不删除物体'
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        root = root_for(context)
        if active(root) is None:
            return {'CANCELLED'}
        data = root.pvm_pose_data
        data.poses.remove(data.index)
        data.index = max(0, min(data.index, len(data.poses) - 1))
        return {'FINISHED'}


class PVM_OT_pose_move(PoseOperator, Operator):
    bl_idname = 'pvm.pose_move'
    bl_label = '移动姿态记录'
    bl_options = {'REGISTER', 'UNDO'}
    step: IntProperty(default=-1, min=-1, max=1, options={'SKIP_SAVE'})

    def execute(self, context):
        data = root_for(context).pvm_pose_data
        target = data.index + self.step
        if self.step not in (-1, 1) or not (0 <= data.index < len(data.poses) and 0 <= target < len(data.poses)):
            return {'CANCELLED'}
        data.poses.move(data.index, target)
        data.index = target
        return {'FINISHED'}


class PVM_UL_poses(UIList):
    def draw_filter(self, context, layout):
        pass

    def filter_items(self, context, data, propname):
        return [], []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, 'name', text='', emboss=False)
        row.label(text=str(len(item.states)))
        if any(state.has_rotation for state in item.states):
            row.label(text='', icon_value=tool_icon('rotate'))
        if any(state.has_location for state in item.states):
            row.label(text='', icon_value=tool_icon('move'))
        row.operator('pvm.pose_apply', text='', icon='PLAY').index = index


class PVM_PT_poses(Panel):
    bl_label = '姿态记录'
    bl_idname = 'PVM_PT_poses'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '显隐管理'

    def draw(self, context):
        layout = self.layout
        root = root_for(context)
        if not root:
            layout.label(text='请先在显隐管理中指定总父级', icon='INFO')
            return
        data = root.pvm_pose_data
        col = layout.column()
        col.enabled = context.mode == 'OBJECT' and root.is_editable and not root.library and not root.override_library
        options = col.row(align=True)
        options.alignment = 'RIGHT'
        options.prop(data, 'record_location', text='', icon_value=tool_icon('move'), toggle=True)
        options.prop(data, 'record_rotation', text='', icon_value=tool_icon('rotate'), toggle=True)
        row = col.row()
        controls = row.column(align=True)
        sub = controls.column(align=True)
        sub.enabled = 0 < data.index < len(data.poses)
        sub.operator('pvm.pose_move', text='', icon='TRIA_UP').step = -1
        sub = controls.column(align=True)
        sub.enabled = 0 <= data.index < len(data.poses) - 1
        sub.operator('pvm.pose_move', text='', icon='TRIA_DOWN').step = 1
        controls.separator()
        controls.operator('pvm.pose_record', text='', icon='ADD')
        sub = controls.column(align=True)
        sub.enabled = active(root) is not None
        sub.operator('pvm.pose_delete', text='', icon='REMOVE')
        controls.separator()
        sub = controls.column(align=True)
        sub.enabled = active(root) is not None
        sub.operator('pvm.pose_update', text='', icon='FILE_REFRESH')
        row.template_list('PVM_UL_poses', '', data, 'poses', data, 'index', rows=4)
        pose = active(root)
        if pose:
            col.prop(pose, 'name', text='重命名')




CLASSES = (PVM_PoseState, PVM_Pose, PVM_PoseData, PVM_OT_pose_record,
           PVM_OT_pose_apply, PVM_OT_pose_update, PVM_OT_pose_delete, PVM_OT_pose_move, PVM_UL_poses, PVM_PT_poses)
