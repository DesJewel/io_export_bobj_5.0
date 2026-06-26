# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8-80 compliant>

bl_info = {
    "name": "Blockbuster extended OBJ format (Blender 5.0)",
    "author": "Campbell Barton, Bastien Montagne, McHorse, DesJewel",
    "version": (0, 2, 1),
    "blender": (4, 2, 0),
    "location": "File > Export",
    "description": "Export Blockbuster OBJ models (meshes, armatures and keyframes)",
    "warning": "",
    "category": "Export"
}

# Support reloading the sub-module when the add-on is reloaded
if "bpy" in locals():
    import importlib
    if "export_bobj" in locals():
        importlib.reload(export_bobj)

import bpy
from bpy.props import (BoolProperty, FloatProperty, StringProperty, EnumProperty)
from bpy_extras.io_utils import (ExportHelper, orientation_helper, path_reference_mode, axis_conversion)


# Export panel
#
# Blender 2.8 replaced the ``orientation_helper_factory`` generator with a
# simple ``orientation_helper`` class decorator, so we use that here.
@orientation_helper(axis_forward='Z', axis_up='Y')
class ExportOBJ(bpy.types.Operator, ExportHelper):
    # Panel's information
    bl_idname = "export_scene.bobj"
    bl_label = 'Export Blockbuster OBJ'
    bl_options = {'PRESET'}

    # Panel's properties (Blender 2.8+ requires the annotation ``:`` syntax
    # for properties instead of plain ``=`` assignment)
    filename_ext = ".bobj"
    filter_glob: StringProperty(default="*.bobj", options={'HIDDEN'})
    use_selection: BoolProperty(name="Selection Only", description="Export selected objects only", default=False)
    include_geometry: BoolProperty(name="Export geometry", description="Include meshes in the model's file", default=True)
    include_keyframes: BoolProperty(name="Export keyframes", description="Include actions in the model's file", default=True)
    keep_vertex_order: BoolProperty(name="Keep Vertex Order", description="", default=False)
    path_mode: path_reference_mode
    check_extension = True

    def execute(self, context):
        from . import export_bobj
        from mathutils import Matrix

        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "check_existing", "filter_glob", "path_mode"))
        # Blender 2.8 switched matrix/vector multiplication from ``*`` to ``@``
        keywords["global_matrix"] = Matrix.Scale(1, 4) @ axis_conversion(to_forward=self.axis_forward, to_up=self.axis_up).to_4x4()

        return export_bobj.save(context, **keywords)


# Register and stuff
def menu_func_export(self, context):
    self.layout.operator(ExportOBJ.bl_idname, text="Blockbuster OBJ (.bobj)")


classes = (
    ExportOBJ,
)


def register():
    # ``register_module`` was removed in 2.8 in favour of ``register_class``
    for cls in classes:
        bpy.utils.register_class(cls)
    # ``INFO_MT_file_export`` was renamed to ``TOPBAR_MT_file_export`` in 2.8
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
