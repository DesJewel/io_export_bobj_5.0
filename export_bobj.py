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

# <pep8 compliant>

import os

import bmesh
import bpy
import mathutils


# ----------------------------------------------------------------------------
# Minimal progress-report shim.
#
# The bundled ``progress_report`` helper module was removed from Blender when
# the OBJ exporter was rewritten in C, so we provide a tiny drop-in replacement
# implementing only the (context-manager / step) interface this script uses.
# ----------------------------------------------------------------------------
class ProgressReport:
    def __init__(self, wm=None):
        self.wm = wm

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def enter_substeps(self, nbr, msg=""):
        if msg:
            print(msg)

    def step(self, msg="", nbr=1):
        if msg:
            print(msg)

    def leave_substeps(self, msg=""):
        if msg:
            print(msg)


class ProgressReportSubstep:
    def __init__(self, progress, nbr, start_msg="", end_msg=""):
        self.progress = progress
        self.end_msg = end_msg
        if start_msg:
            print(start_msg)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.end_msg:
            print(self.end_msg)
        return False

    def enter_substeps(self, nbr, msg=""):
        if msg:
            print(msg)

    def step(self, msg="", nbr=1):
        if msg:
            print(msg)

    def leave_substeps(self, msg=""):
        if msg:
            print(msg)


# Remove spaces from given string (so it would be spaceless)
def name_compat(name):
    return 'None' if name is None else name.replace(' ', '_')


# Triangulate polygons in given mesh
def mesh_triangulate(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()


# Write given armature to given file with applied matrix
def write_armature(fw, armature, global_matrix):
    fw('# Armature data\n')
    fw('arm_name %s\n' % armature.data.name)

    if armature.animation_data is not None and armature.animation_data.action is not None:
        fw('arm_action %s\n' % name_compat(armature.animation_data.action.name))

    for bone in armature.data.bones:
        parent = name_compat(bone.parent.name) if bone.parent is not None else ''

        tail = bone.matrix_local.copy()
        tail.translation = bone.tail_local
        # Blender 2.8 switched matrix multiplication from ``*`` to ``@``
        tail = global_matrix @ armature.matrix_world @ tail

        vx, vy, vz = tail.translation[:]

        mat = global_matrix @ armature.matrix_world @ bone.matrix_local

        if bone.parent:
            mat = global_matrix @ armature.matrix_world @ bone.matrix_local

        m = ""

        for xx in range(0, 4):
            for yy in range(0, 4):
                m += str(mat.row[xx][yy]) + ' '

        # Write the bone to the file (name, parent name,)
        string = 'arm_bone %s %s ' % (name_compat(bone.name), parent)
        string += '%f %f %f ' % (vx, vy, vz)
        string += m + '\n'

        fw(string)


# Iterate over every F-Curve of an action, across Blender versions.
#
# Blender 4.4 introduced "slotted actions" and Blender 5.0 *removed* the legacy
# ``Action.fcurves`` collection entirely. F-Curves now live under
# ``action.layers[].strips[].channelbags[].fcurves`` (one channelbag per slot).
# This helper yields all of them and falls back to the old ``Action.fcurves``
# attribute on Blender 4.3 and earlier.
def iter_action_fcurves(action):
    layers = getattr(action, "layers", None)
    if layers is not None:
        # Blender 4.4+ / 5.x slotted actions
        for layer in layers:
            for strip in layer.strips:
                channelbags = getattr(strip, "channelbags", None)
                if channelbags is None:
                    # Older 4.4 builds may only expose the per-slot accessor
                    slots = getattr(action, "slots", None) or []
                    for slot in slots:
                        try:
                            channelbag = strip.channelbag(slot)
                        except (TypeError, RuntimeError):
                            channelbag = None
                        if channelbag is not None:
                            for fcurve in channelbag.fcurves:
                                yield fcurve
                    continue
                for channelbag in channelbags:
                    for fcurve in channelbag.fcurves:
                        yield fcurve
        return

    # Blender <= 4.3 legacy actions
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        for fcurve in legacy:
            yield fcurve


# Writes all action keyframes
def write_actions(context, fw):
    fw('# Animation data\n')

    # Exporting animation actions
    for key, action in bpy.data.actions.items():
        write_action(context, fw, key, action)


# Write an action
def write_action(context, fw, name, action):
    groups = {}

    def getOrCreate(key):
        if key in groups:
            return groups[key]

        l = []
        groups[key] = l

        return l

    # Collect groups
    for fc in iter_action_fcurves(action):
        if fc.data_path.startswith('pose.bones["'):
            key = fc.data_path[12:]
            key = key[:key.index('"')]

            getOrCreate(key).append(fc)

    # Don't write anything if this action is empty
    if not groups:
        return

    fw('an %s\n' % name)

    for key, group in groups.items():
        fw('ao %s\n' % name_compat(key))

        for fcurve in group:
            data_path = fcurve.data_path
            index = fcurve.array_index
            length = len(fcurve.keyframe_points)
            dvalue = 0

            if data_path.endswith('location'):
                data_path = 'location'
            elif data_path.endswith('rotation_euler'):
                data_path = 'rotation'
            elif data_path.endswith('scale'):
                data_path = 'scale'
                dvalue = 1
            else:
                continue

            if length <= 0:
                continue

            all_default = True

            # Prevent writing actions which fully consist out of default values
            for keyframe in fcurve.keyframe_points:
                if keyframe.co[1] != dvalue:
                    all_default = False

                    break

            if all_default:
                continue

            # Write the action group
            fw('ag %s %d\n' % (data_path, index))

            last_frame = None

            for keyframe in fcurve.keyframe_points:
                # Avoid inserting keyframes with duplicate X value
                if last_frame == keyframe.co[0]:
                    continue

                fw(stringify_keyframe(context, keyframe) + '\n')
                last_frame = keyframe.co[0]


# Stringify a keyframe
def stringify_keyframe(context, keyframe):
    fps = context.scene.render.fps
    f = 20 / fps

    interp = keyframe.interpolation
    result = 'kf %d %f %s' % (keyframe.co[0] * f, keyframe.co[1], interp)
    result += ' %f %f %f %f' % (keyframe.handle_left[0] * f, keyframe.handle_left[1], keyframe.handle_right[0] * f, keyframe.handle_right[1])

    return result


def save(context,
         filepath,
         *,
         keep_vertex_order=False,
         use_selection=True,
         include_keyframes=True,
         include_geometry=True,
         global_matrix=None):

    _write(context, filepath,
           EXPORT_KEEP_VERT_ORDER=keep_vertex_order,
           EXPORT_SEL_ONLY=use_selection,
           EXPORT_KEYFRAMES=include_keyframes,
           EXPORT_GEOMETRY=include_geometry,
           EXPORT_GLOBAL_MATRIX=global_matrix,
           )

    return {'FINISHED'}


def _write(context, filepath,
           EXPORT_KEEP_VERT_ORDER,
           EXPORT_SEL_ONLY,
           EXPORT_KEYFRAMES,
           EXPORT_GEOMETRY,
           EXPORT_GLOBAL_MATRIX):
    with ProgressReport(context.window_manager) as progress:
        scene = context.scene

        # Exit edit mode before exporting, so current object states are exported properly.
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')

        objects = context.selected_objects if EXPORT_SEL_ONLY else scene.objects

        progress.enter_substeps(1)
        write_file(context, filepath, objects, scene,
                   EXPORT_KEEP_VERT_ORDER,
                   EXPORT_GLOBAL_MATRIX,
                   EXPORT_KEYFRAMES,
                   EXPORT_GEOMETRY,
                   progress)
        progress.leave_substeps()


def write_file(context, filepath, objects, scene,
               EXPORT_KEEP_VERT_ORDER=False,
               EXPORT_GLOBAL_MATRIX=None,
               EXPORT_KEYFRAMES=True,
               EXPORT_GEOMETRY=True,
               progress=ProgressReport()):
    if EXPORT_GLOBAL_MATRIX is None:
        EXPORT_GLOBAL_MATRIX = mathutils.Matrix()

    def veckey3d(v):
        return round(v.x, 4), round(v.y, 4), round(v.z, 4)

    def veckey2d(v):
        return round(v[0], 5), round(v[1], 5)

    with ProgressReportSubstep(progress, 2, "BOBJ Export path: %r" % filepath, "BOBJ Export Finished") as subprogress1:
        with open(filepath, "w", encoding="utf8", newline="\n") as f:
            fw = f.write

            # Write Header
            fw('# Blender v%s Blockbuster OBJ File: %r\n' % (bpy.app.version_string, os.path.basename(bpy.data.filepath)))
            fw('# www.blender.org\n')

            # Initialize totals, these are updated each object
            totverts = totuvco = totno = 1
            face_vert_index = 1

            # Export all meshes
            if EXPORT_GEOMETRY:
                # The dependency graph is needed to evaluate objects in 2.8+
                depsgraph = context.evaluated_depsgraph_get()

                subprogress1.enter_substeps(len(objects))
                for i, ob_main in enumerate(objects):
                    # The old "dupli" instancing API was removed in 2.8; just
                    # export the object itself.
                    obs = [(ob_main, ob_main.matrix_world)]

                    subprogress1.enter_substeps(len(obs))
                    for ob, ob_mat in obs:
                        with ProgressReportSubstep(subprogress1, 6) as subprogress2:
                            uv_unique_count = no_unique_count = 0

                            # Exporting armature data
                            if ob.type == 'ARMATURE':
                                write_armature(fw, ob, EXPORT_GLOBAL_MATRIX)

                            # Build a temporary mesh. We call ``to_mesh`` on the
                            # ORIGINAL object (not the evaluated one) so modifiers
                            # are NOT applied -- the armature deformation must stay
                            # un-baked so vertex weights + keyframes export cleanly.
                            # ``preserve_all_data_layers`` keeps vertex groups/UVs.
                            try:
                                me = ob.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
                            except RuntimeError:
                                me = None

                            if me is None:
                                continue

                            # Transform object's and global matrix and triangulate the mesh
                            me.transform(EXPORT_GLOBAL_MATRIX @ ob_mat)
                            mesh_triangulate(me)

                            # Prepare UV data ("uv_textures" was merged into
                            # "uv_layers" in 2.8)
                            faceuv = len(me.uv_layers) > 0

                            if faceuv:
                                uv_layer = me.uv_layers.active.data[:]

                            me_verts = me.vertices[:]

                            # Make our own list so it can be sorted to reduce context switching
                            face_index_pairs = [(face, index) for index, face in enumerate(me.polygons)]

                            # If there is no data to write, skip it
                            if not (len(face_index_pairs) + len(me.vertices)):
                                ob.to_mesh_clear()
                                continue

                            loops = me.loops

                            # Compute per-corner (split) normals.
                            #   - Blender < 4.1: Mesh.calc_normals_split() + loop.normal
                            #   - Blender >= 4.1: Mesh.corner_normals collection
                            me_loop_normals = []
                            if face_index_pairs:
                                if hasattr(me, "calc_normals_split"):
                                    me.calc_normals_split()
                                    me_loop_normals = [loops[li].normal.copy() for li in range(len(loops))]
                                else:
                                    me_loop_normals = [cn.vector.copy() for cn in me.corner_normals]

                            # Sort by material then smoothing, so we don't over
                            # context switch in the obj file. (Per-face images no
                            # longer exist in 2.8, so they're not part of the key.)
                            face_index_pairs.sort(key=lambda a: (a[0].material_index, a[0].use_smooth))

                            fw('# Mesh data\n')
                            # Write out the object's name and parent armature (if it has any)
                            fw('o %s\n' % name_compat(ob.name))

                            if ob.parent and ob.parent.type == 'ARMATURE':
                                fw('o_arm %s\n' % name_compat(ob.parent.data.name))

                            subprogress2.step()

                            # Write vertices and weights
                            for v in me_verts:
                                fw('v %.6f %.6f %.6f\n' % v.co[:])

                                for vgroup in v.groups:
                                    fw('vw %s %.6f\n' % (name_compat(ob.vertex_groups[vgroup.group].name), vgroup.weight))

                            subprogress2.step()

                            # Export UVs
                            uv_face_mapping = [None] * len(face_index_pairs)

                            if faceuv:
                                uv = f_index = uv_index = uv_key = uv_val = uv_ls = None

                                uv_dict = {}
                                uv_get = uv_dict.get
                                for f, f_index in face_index_pairs:
                                    uv_ls = uv_face_mapping[f_index] = []
                                    for uv_index, l_index in enumerate(f.loop_indices):
                                        uv = uv_layer[l_index].uv
                                        uv_key = loops[l_index].vertex_index, veckey2d(uv)

                                        uv_val = uv_get(uv_key)
                                        if uv_val is None:
                                            uv_val = uv_dict[uv_key] = uv_unique_count
                                            fw('vt %.4f %.4f\n' % uv[:])
                                            uv_unique_count += 1
                                        uv_ls.append(uv_val)

                                del uv_dict, uv, f_index, uv_index, uv_ls, uv_get, uv_key, uv_val
                            else:
                                # No UV layer present: emit a single default UV
                                # coordinate and map every face corner to it so
                                # the face section below stays valid.
                                fw('vt 0.0 0.0\n')
                                uv_unique_count = 1
                                for f, f_index in face_index_pairs:
                                    uv_face_mapping[f_index] = [0] * len(f.loop_indices)

                            subprogress2.step()

                            # Export normals
                            no_key = no_val = None
                            normals_to_idx = {}
                            no_get = normals_to_idx.get
                            loops_to_normals = [0] * len(loops)
                            for f, f_index in face_index_pairs:
                                for l_idx in f.loop_indices:
                                    no_key = veckey3d(me_loop_normals[l_idx])
                                    no_val = no_get(no_key)
                                    if no_val is None:
                                        no_val = normals_to_idx[no_key] = no_unique_count
                                        fw('vn %.4f %.4f %.4f\n' % no_key)
                                        no_unique_count += 1
                                    loops_to_normals[l_idx] = no_val
                            del normals_to_idx, no_get, no_key, no_val

                            subprogress2.step()

                            # Finally write out face indices
                            for f, f_index in face_index_pairs:
                                f_v = [(vi, me_verts[v_idx], l_idx) for vi, (v_idx, l_idx) in enumerate(zip(f.vertices, f.loop_indices))]

                                fw('f')
                                for vi, v, li in f_v:
                                    # vertex, UV, normal
                                    fw(" %d/%d/%d" % (totverts + v.index, totuvco + uv_face_mapping[f_index][vi], totno + loops_to_normals[li]))

                                    face_vert_index += len(f_v)
                                fw('\n')

                            subprogress2.step()

                            # Make the indices global rather then per mesh
                            totverts += len(me_verts)
                            totuvco += uv_unique_count
                            totno += no_unique_count

                            # clean up the temporary mesh (replaces the old
                            # bpy.data.meshes.remove call)
                            ob.to_mesh_clear()

                    subprogress1.leave_substeps("Finished writing geometry of '%s'." % ob_main.name)

                subprogress1.leave_substeps()

            # Write keyframes to the file
            if EXPORT_KEYFRAMES:
                write_actions(context, fw)

        subprogress1.step("Finished exporting geometry")
